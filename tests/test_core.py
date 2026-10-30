import hashlib, io, json, os, random, tempfile, threading, unittest
from pathlib import Path
from PIL import Image
from funkerlitelab.operation import optimize_mod
from funkerlitelab.paths import validate_roots, PathError
from funkerlitelab.png_optimizer import build_candidate
from funkerlitelab.scanner import scan, summarize


def tree_hash(root):
    h = {}
    for dp, _, fn in os.walk(root):
        for n in fn:
            p = Path(dp) / n
            h[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return h


def make_mod(root):
    root.mkdir()
    grad = Image.new("RGBA", (64, 64))
    grad.putdata([(x * 4 % 256, y * 4 % 256, 128, (x * 7) % 256) for y in range(64) for x in range(64)])
    grad.save(root / "weak.png", compress_level=0)                       # smaller candidate expected
    noise = Image.frombytes("RGBA", (32, 32), random.Random(1).randbytes(32 * 32 * 4))
    noise.save(root / "noise.png", compress_level=9, optimize=True)      # likely not smaller
    pal = Image.new("P", (40, 40)); pal.putpalette([i % 256 for i in range(768)])
    pal.putdata([i % 7 for i in range(1600)]); pal.save(root / "pal.png", compress_level=0, transparency=0)
    Image.new("L", (30, 30), 77).save(root / "gray.png", compress_level=0)
    Image.new("RGBA", (20, 20), (0, 0, 0, 0)).save(root / "clear.png", compress_level=0)
    (root / "bad.png").write_bytes(b"not a png")
    (root / "images").mkdir()
    (root / "images" / "ok.json").write_text('{"image":"x"}')
    (root / "images" / "broken.json").write_text('{"image":')
    (root / "images" / "a.xml").write_text("<TextureAtlas/>")
    (root / "mystery.xyz").write_bytes(b"\x00\x01")
    (root / "song.ogg").write_bytes(b"OggS")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        self.src = self.t / "src"
        make_mod(self.src)
        self.ws = self.t / "ws"

    def tearDown(self):
        self.tmp.cleanup()


class TestPaths(Base):
    def test_overlap_and_collision(self):
        with self.assertRaises(PathError): validate_roots(self.src, self.src / "out")
        with self.assertRaises(PathError): validate_roots(self.src, self.t)
        with self.assertRaises(PathError): validate_roots(self.src, self.src / ".." / "src" / "x")
        (self.t / "exists").mkdir()
        with self.assertRaises(PathError) as c: validate_roots(self.src, self.t / "exists")
        self.assertEqual(c.exception.code, "DESTINATION_EXISTS")
        with self.assertRaises(PathError): validate_roots(self.t / "nope")
        with self.assertRaises(PathError): validate_roots(self.src, None, self.src / "ws")

    def test_prefix_lookalike_is_not_overlap(self):
        validate_roots(self.src, self.t / "src2")  # "src2" shares a string prefix with "src"


class TestScanner(Base):
    def test_inventory(self):
        recs = list(scan(self.src))
        names = {r.rel_path for r in recs}
        self.assertIn("mystery.xyz", names)
        s = summarize(recs)
        self.assertEqual(s["file_count"], 11)
        self.assertEqual(s["total_bytes"], sum(p.stat().st_size for p in self.src.rglob("*") if p.is_file()))
        self.assertEqual(s["parse_failures"], [os.path.join("images", "broken.json")])
        self.assertEqual(s["unknown_type_files"], 1)

    def test_symlink_not_followed(self):
        os.symlink(self.t, self.src / "loop")
        recs = list(scan(self.src))
        self.assertTrue(any(r.is_symlink for r in recs))
        self.assertEqual(len(recs), 12)


class TestPng(Base):
    def test_candidates(self):
        res = {n: build_candidate(self.src / n) for n in
               ["weak.png", "noise.png", "pal.png", "gray.png", "clear.png", "bad.png"]}
        for n in ["weak.png", "pal.png", "gray.png", "clear.png"]:
            r, data = res[n]
            self.assertEqual(r.status, "SUCCESS", (n, r.reason))
            self.assertTrue(r.pixel_verified)
            self.assertLess(len(data), r.original_size)
            self.assertEqual(r.dims_before, r.dims_after)
        r, data = res["noise.png"]
        self.assertIsNone(data)  # never accept a non-smaller candidate
        r, data = res["bad.png"]
        self.assertEqual(r.status, "FAILED"); self.assertIsNone(data)

    def test_pixels_identical_incl_transparency(self):
        r, data = build_candidate(self.src / "pal.png")
        a = Image.open(self.src / "pal.png"); b = Image.open(io.BytesIO(data))
        self.assertEqual(a.convert("RGBA").tobytes(), b.convert("RGBA").tobytes())
        self.assertEqual(a.info.get("transparency"), b.info.get("transparency"))

    def test_pixel_limit_skips(self):
        r, data = build_candidate(self.src / "weak.png", max_pixels=10)
        self.assertEqual(r.status, "SKIPPED"); self.assertIsNone(data)


class TestOperation(Base):
    def test_dry_run_changes_nothing(self):
        before = tree_hash(self.src)
        m = optimize_mod(self.src, self.ws)
        self.assertEqual(tree_hash(self.src), before)
        self.assertEqual(m["mode"], "dry-run")
        self.assertEqual(m["summary"]["files_changed"], 0)
        self.assertGreater(m["summary"]["dry_run_potential_bytes"], 0)
        self.assertEqual(list(self.t.glob("*out*")), [])
        self.assertTrue(list(self.ws.glob("manifest-*.json")))

    def test_apply_end_to_end(self):
        before = tree_hash(self.src)
        out = self.t / "out"
        m = optimize_mod(self.src, self.ws, out, apply=True)
        self.assertIn(m["status"], ("SUCCESS", "WARNING"))
        self.assertEqual(tree_hash(self.src), before)            # source untouched
        after = tree_hash(out)
        self.assertEqual(set(after), set(before))
        changed = {k for k in after if after[k] != before[k]}
        self.assertEqual(changed, {i["rel_path"] for i in m["images"] if i["applied"]})
        for rel in changed:
            a, b = Image.open(self.src / rel), Image.open(out / rel)
            self.assertEqual(a.size, b.size)
            self.assertEqual(a.convert("RGBA").tobytes(), b.convert("RGBA").tobytes())
        s = m["summary"]
        actual_saved = sum((self.src / k).stat().st_size - (out / k).stat().st_size for k in changed)
        self.assertEqual(s["png_original_bytes"] - s["png_final_bytes"], actual_saved)
        self.assertFalse([p for p in self.t.iterdir() if "flab-tmp" in p.name])
        self.assertEqual(json.loads(next(self.ws.glob("manifest-*.json")).read_text())["status"], m["status"])

    def test_destination_collision_refused(self):
        out = self.t / "out"; out.mkdir(); (out / "keep.txt").write_text("user data")
        with self.assertRaises(PathError): optimize_mod(self.src, self.ws, out, apply=True)
        self.assertEqual((out / "keep.txt").read_text(), "user data")

    def test_cancel_leaves_no_output(self):
        ev = threading.Event(); ev.set()
        out = self.t / "out"
        m = optimize_mod(self.src, self.ws, out, apply=True, cancel=ev)
        self.assertEqual(m["status"], "CANCELLED")
        self.assertFalse(out.exists())
        self.assertFalse([p for p in self.t.iterdir() if "flab-tmp" in p.name])

    def test_failure_cleans_staging(self):
        import funkerlitelab.operation as op
        orig = op.build_candidate
        op.build_candidate = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            out = self.t / "out"
            m = optimize_mod(self.src, self.ws, out, apply=True)
        finally:
            op.build_candidate = orig
        self.assertEqual(m["status"], "FAILED"); self.assertFalse(out.exists())
        self.assertFalse([p for p in self.t.iterdir() if "flab-tmp" in p.name])


if __name__ == "__main__":
    unittest.main(verbosity=2)
