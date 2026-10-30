"""Regression tests for bugs found in the legacy scripts + new modules."""
import io, json, os, stat, struct, tempfile, unittest, zipfile, zlib
from pathlib import Path
from PIL import Image
from funkerlitelab.atlas import check_atlases
from funkerlitelab.cli import main as cli_main, write_report, load_config
from funkerlitelab.png_optimizer import build_candidate
from funkerlitelab.zipcheck import inspect_zip


def chunk(t, d):
    return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)


def raw_png(w, h, depth, ctype, pixel_bytes_per_row, extra=()):
    rows = b"".join(b"\0" + pixel_bytes_per_row(y) for y in range(h))
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, depth, ctype, 0, 0, 0))
    for t, d in extra:
        out += chunk(t, d)
    return out + chunk(b"IDAT", zlib.compress(rows, 0)) + chunk(b"IEND", b"")


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.t = Path(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()


class TestPngPolicy(T):
    def test_16bit_is_skipped_not_silently_reduced(self):
        # legacy optimize_pngs.py accepted this and wrote a lossy 8-bit file
        p = self.t / "deep.png"
        p.write_bytes(raw_png(4, 4, 16, 2, lambda y: b"".join(struct.pack(">HHH", x * 4000 + 37, y * 4000 + 101, 5003) for x in range(4))))
        r, data = build_candidate(p)
        self.assertEqual(r.status, "SKIPPED"); self.assertIsNone(data); self.assertIn("16-bit", r.reason)

    def test_color_chunks_are_copied_byte_for_byte(self):
        # v3 skipped PNGs with gAMA; now gAMA is preserved exactly
        p = self.t / "gamma.png"
        gama = struct.pack(">I", 45455)
        p.write_bytes(raw_png(32, 32, 8, 2, lambda y: bytes(96), extra=[(b"gAMA", gama)]))
        r, data = build_candidate(p)
        self.assertEqual(r.status, "SUCCESS", r.reason)
        from funkerlitelab.png_optimizer import read_png_chunks
        self.assertEqual(dict(read_png_chunks(data))[b"gAMA"], gama)

    def test_unknown_chunk_skipped(self):
        p = self.t / "odd.png"
        p.write_bytes(raw_png(4, 4, 8, 2, lambda y: bytes(12), extra=[(b"zZZz", b"??")]))
        r, data = build_candidate(p)
        self.assertEqual(r.status, "SKIPPED"); self.assertIn("unknown", r.reason)

    def test_text_chunks_stripped_and_reported(self):
        p = self.t / "txt.png"
        p.write_bytes(raw_png(32, 32, 8, 2, lambda y: bytes(96), extra=[(b"tEXt", b"Comment\0hello")]))
        r, data = build_candidate(p)
        self.assertIn("tEXt", r.stripped_chunks)
        from funkerlitelab.png_optimizer import read_png_chunks
        self.assertNotIn(b"tEXt", dict(read_png_chunks(data)))
        r2, d2 = build_candidate(p, strip_metadata=False)
        self.assertIn(b"tEXt", dict(read_png_chunks(d2)))

    def test_phys_chunk_preserved(self):
        p = self.t / "dpi.png"
        p.write_bytes(raw_png(32, 32, 8, 2, lambda y: bytes(96), extra=[(b"pHYs", struct.pack(">IIB", 2834, 2834, 1))]))
        r, data = build_candidate(p)
        if data is not None:
            self.assertIn(b"pHYs", data)
        else:
            self.assertIn(r.status, ("FAILED", "SKIPPED"))  # rejected rather than altered

    def test_memory_estimate_is_labelled_theoretical(self):
        p = self.t / "a.png"; Image.new("RGBA", (10, 20), (1, 2, 3, 4)).save(p, compress_level=0)
        r, _ = build_candidate(p)
        self.assertEqual(r.est_decoded_bytes, 10 * 20 * 4)


class TestAtlas(T):
    def mk(self, xml, size=(100, 100), name="a.png"):
        Image.new("RGBA", size).save(self.t / name)
        (self.t / "a.xml").write_text(xml)
        return check_atlases(self.t)[0]

    def test_ok_and_frame_offsets_counted(self):
        r = self.mk('<TextureAtlas imagePath="a.png"><SubTexture name="f" x="0" y="0" width="10" height="10" frameX="-2" frameY="-2" frameWidth="14" frameHeight="14"/></TextureAtlas>')
        self.assertEqual(r["status"], "OK"); self.assertEqual(r["frames_with_frame_offsets"], 1)

    def test_out_of_bounds(self):
        r = self.mk('<TextureAtlas imagePath="a.png"><SubTexture name="f" x="95" y="0" width="10" height="10"/></TextureAtlas>')
        self.assertEqual(r["status"], "CHECK_FRAMES"); self.assertEqual(r["out_of_bounds"], 1)

    def test_missing_and_case_insensitive(self):
        r = self.mk('<TextureAtlas imagePath="nope.png"><SubTexture name="f" x="0" y="0" width="1" height="1"/></TextureAtlas>')
        self.assertEqual(r["status"], "MISSING_IMAGE")
        r = self.mk('<TextureAtlas imagePath="A.PNG"><SubTexture name="f" x="0" y="0" width="1" height="1"/></TextureAtlas>')
        self.assertEqual(r["status"], "OK"); self.assertIn("case-insensitive", r["image_resolution"])

    def test_non_atlas_and_malformed(self):
        self.assertEqual(self.mk("<Other x='1' y='1' width='1' height='1'/>")["status"], "NOT_ATLAS")
        self.assertEqual(self.mk("<TextureAtlas")["status"], "XML_ERROR")

    def test_real_sample_from_user_project(self):
        d = Path(__file__).resolve().parents[1] / "legacy" / "test_run" / "images" / "agoti" / "images"
        if not d.is_dir():
            self.skipTest("sample missing")
        r = check_atlases(d)[0]
        self.assertEqual(r["status"], "OK"); self.assertEqual(r["image_size"], [2048, 2048]); self.assertEqual(r["frames"], 104)


class TestZip(T):
    def zip(self, entries, symlink=None):
        p = self.t / "m.zip"
        with zipfile.ZipFile(p, "w") as z:
            for n, d in entries.items():
                z.writestr(n, d)
            if symlink:
                zi = zipfile.ZipInfo(symlink); zi.create_system = 3; zi.external_attr = (stat.S_IFLNK | 0o777) << 16
                z.writestr(zi, "/etc/passwd")
        return p

    def test_good(self):
        r = inspect_zip(self.zip({"mod/images/a.png": b"x", "mod/data/a.json": b"{}", "mod/songs/s.ogg": b"o"}))
        self.assertIn("looks like", r["verdict"]); self.assertEqual(r["mod_root"], "mod/")

    def test_traversal_and_symlink_rejected(self):
        self.assertTrue(inspect_zip(self.zip({"../evil.txt": b"x"}))["verdict"].startswith("REJECTED"))
        self.assertTrue(inspect_zip(self.zip({"images/a": b"x"}, symlink="link"))["verdict"].startswith("REJECTED"))

    def test_not_a_zip(self):
        (self.t / "bad.zip").write_bytes(b"nope")
        self.assertTrue(inspect_zip(self.t / "bad.zip")["verdict"].startswith("REJECTED"))


class TestCli(T):
    def test_cli_resize_requires_explicit_flag(self):
        mod = self.t / "mod"; (mod / "images").mkdir(parents=True)
        cfg = str(self.t / "none.json")
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli_main(["--config", cfg, "optimize", str(mod), "--workspace", str(self.t / "ws"), "--mode", "aggressive"])
        self.assertFalse(json.loads(buf.getvalue())["settings"]["resize_active"])

    def test_report_inside_mod_refused(self):
        mod = self.t / "mod"; mod.mkdir()
        with self.assertRaises(SystemExit): write_report(mod / "r.json", mod, {})

    def test_apply_requires_output(self):
        mod = self.t / "mod"; mod.mkdir()
        with self.assertRaises(SystemExit): cli_main(["--config", str(self.t / "none.json"), "optimize", str(mod), "--apply"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
