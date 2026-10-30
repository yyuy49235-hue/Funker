"""Stage A (extra lossless techniques) and Stage B (user-approved resize) + target strategy."""
import hashlib, json, os, random, shutil, tempfile, threading, unittest
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter
from funkerlitelab.atlas_scale import ScaleError, compensate_character_json, scale_sparrow_xml
from funkerlitelab.operation import Settings, optimize_mod, reduction_pct, get_progress
from funkerlitelab.png_optimizer import build_candidate, rgba_equal
from funkerlitelab.paths import PathError


def art(w, h, seed):
    rnd = random.Random(seed)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    for _ in range(80):
        x, y = rnd.randint(0, w - 300), rnd.randint(0, h - 300)
        d.ellipse([x, y, x + rnd.randint(60, 290), y + rnd.randint(60, 290)],
                  fill=(rnd.randint(0, 255), rnd.randint(0, 255), rnd.randint(0, 255), rnd.randint(90, 255)))
    return im.filter(ImageFilter.GaussianBlur(1.5))


def atlas_xml(image, w, h, grid=8, trimmed=True):
    fw, fh = w // grid, h // grid
    rows = []
    for i in range(grid * grid):
        x, y = (i % grid) * fw, (i // grid) * fh
        trim = f' frameX="-{(i % 5) * 4}" frameY="-{(i % 3) * 2}" frameWidth="{fw + 20}" frameHeight="{fh + 8}"' if trimmed else ""
        rows.append(f'\t<SubTexture name="idle{i:04d}" x="{x}" y="{y}" width="{fw}" height="{fh}"{trim}/>')
    return f'<?xml version="1.0" encoding="utf-8"?>\n<TextureAtlas imagePath="{image}">\n' + "\n".join(rows) + "\n</TextureAtlas>\n"


CHAR_JSON = '{\n\t"animations": [{"anim": "idle", "name": "idle", "fps": 24, "loop": false, "offsets": [0, 0]}],\n\t"image": "characters/%s",\n\t"scale": %s,\n\t"position": [0, 0]\n}\n'


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.TemporaryDirectory(); b = Path(cls.base.name) / "mod"
        (b / "images/characters").mkdir(parents=True); (b / "characters").mkdir(); (b / "scripts").mkdir()
        art(2048, 2048, 1).save(b / "images/characters/Hero.png", compress_level=6)
        (b / "images/characters/Hero.xml").write_text(atlas_xml("Hero.png", 2048, 2048))
        (b / "characters/hero.json").write_text(CHAR_JSON % ("Hero", "1.2"))
        art(2048, 1024, 2).save(b / "images/characters/Villain.png", compress_level=6)
        (b / "images/characters/Villain.xml").write_text(atlas_xml("Villain.png", 2048, 1024))
        (b / "characters/villain.json").write_text(CHAR_JSON % ("Villain", "1"))
        art(2048, 2048, 3).save(b / "images/stagebg.png", compress_level=6)            # used by Lua: must be blocked
        (b / "scripts/stage.lua").write_text("makeLuaSprite('bg', 'stagebg', 0, 0)\n")
        flat = Image.new("RGBA", (256, 256), (0, 0, 0, 0)); d = ImageDraw.Draw(flat)
        for i in range(30): d.rectangle([i * 8, i * 8, i * 8 + 40, i * 8 + 40], fill=[(255, 0, 0, 255), (0, 0, 255, 255), (0, 0, 0, 0)][i % 3])
        flat.save(b / "images/flat.png", compress_level=1)
        cls.mod = b

    @classmethod
    def tearDownClass(cls):
        cls.base.cleanup()

    def setUp(self):
        self.t = Path(tempfile.mkdtemp()); self.src = self.t / "mod"
        shutil.copytree(self.mod, self.src); self.ws = self.t / "ws"

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def tree(self, root):
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(root).rglob("*") if p.is_file()}


class TestLosslessTechniques(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.t = Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()

    def check(self, im, name, **save):
        p = self.t / name; im.save(p, **save)
        r, data = build_candidate(p)
        self.assertIsNotNone(data, r.reason)
        import io; cand = Image.open(io.BytesIO(data)); cand.load()
        self.assertTrue(rgba_equal(Image.open(p), cand)); self.assertEqual(cand.size, im.size)
        return r

    def test_few_colors_become_palette_with_big_saving(self):
        im = Image.new("RGBA", (300, 300), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        for i in range(25): d.rectangle([i * 9, i * 9, i * 9 + 50, i * 9 + 50], fill=[(255, 0, 0, 255), (0, 0, 255, 128), (9, 9, 9, 255)][i % 3])
        r = self.check(im, "f.png", compress_level=6)
        self.assertTrue(r.technique.startswith("palette")); self.assertEqual(r.mode_after, "P")
        self.assertGreater(100 * (r.original_size - r.candidate_size) / r.original_size, 40)

    def test_opaque_rgba_drops_alpha_and_gray_becomes_L(self):
        r = self.check(Image.new("RGBA", (200, 200), (10, 20, 30, 255)).filter(ImageFilter.GaussianBlur(0)), "o.png", compress_level=1)
        self.assertIn(r.mode_after, ("RGB", "P"))
        g = Image.effect_noise((128, 128), 40).convert("RGB")
        r = self.check(g, "g.png", compress_level=1); self.assertEqual(r.mode_after, "L")

    def test_smooth_art_gains_little_and_says_so(self):
        p = self.t / "aa.png"; art(512, 512, 5).save(p, compress_level=6)
        r, data = build_candidate(p)
        pct = 100 * (r.original_size - (r.candidate_size if data else r.original_size)) / r.original_size
        self.assertLess(pct, 10)   # honest limit of lossless on anti-aliased art


class TestAtlasMath(unittest.TestCase):
    XML = '<TextureAtlas imagePath="a.png">\n<SubTexture name="a" x="0" y="0" width="3" height="4" frameX="-2" frameY="-2" frameWidth="7" frameHeight="8"/>\n<SubTexture name="b" x="3" y="0" width="3" height="4"/>\n</TextureAtlas>'

    def test_edges_scaled_no_gap_and_frame_offsets_scaled(self):
        new, n = scale_sparrow_xml(self.XML, 0.5, 0.5, 4, 2)
        self.assertEqual(n, 2)
        import xml.etree.ElementTree as ET
        a, b = [x for x in ET.fromstring(new).iter("SubTexture")]
        self.assertEqual(int(a.get("x")) + int(a.get("width")), int(b.get("x")))   # still adjacent
        self.assertEqual((a.get("frameX"), a.get("frameWidth"), a.get("frameHeight")), ("-1", "4", "4"))
        self.assertIn('imagePath="a.png"', new)

    def test_out_of_bounds_rejected(self):
        with self.assertRaises(ScaleError): scale_sparrow_xml(self.XML, 1.0, 1.0, 4, 2)

    def test_json_scale_compensation_exact_and_minimal(self):
        txt = CHAR_JSON % ("Hero", "1.2")
        new, old, s = compensate_character_json(txt, 0.5)
        self.assertEqual((old, s), (1.2, 2.4)); self.assertEqual(new.replace("2.4", "1.2"), txt)
        new, old, s = compensate_character_json(txt.replace('\t"scale": 1.2,\n', ""), 0.5)
        self.assertEqual(json.loads(new)["scale"], 2.0)
        with self.assertRaises(ScaleError): compensate_character_json("{not json", 0.5)
        with self.assertRaises(ScaleError): compensate_character_json('{"scale": "big"}', 0.5)


class TestResizePipeline(Fixture):
    def run_mod(self, **kw):
        return optimize_mod(self.src, self.ws, kw.pop("output", None), kw.pop("apply", False), settings=Settings(**kw))

    def test_lossless_mode_never_resizes_even_if_flag_set(self):
        m = self.run_mod(mode="lossless", allow_resize=True)
        self.assertEqual(m["summary"]["optimized_resized"], 0); self.assertFalse(m["settings"]["resize_active"])

    def test_resize_needs_explicit_permission(self):
        m = self.run_mod(mode="balanced", allow_resize=False)
        self.assertEqual(m["summary"]["optimized_resized"], 0)

    def test_balanced_resize_end_to_end(self):
        before = self.tree(self.src); out = self.t / "out"
        m = self.run_mod(mode="balanced", allow_resize=True, scale=0.5, target_pct=45, output=out, apply=True)
        self.assertIn(m["status"], ("SUCCESS", "WARNING"), m["errors"])
        self.assertEqual(self.tree(self.src), before)                                   # original untouched
        s = m["summary"]; self.assertGreater(s["optimized_resized"], 0)
        # byte-accurate totals, checked against the files on disk
        disk = sum((out / i["rel_path"]).stat().st_size for i in m["images"])
        self.assertEqual(disk, s["png_final_bytes"]); self.assertEqual(disk, m["disk_verified_png_final_bytes"])
        self.assertAlmostEqual(s["total_reduction_pct"], 100 * (s["png_original_bytes"] - disk) / s["png_original_bytes"])
        self.assertEqual(s["lossless_saved_bytes"] + s["resize_saved_bytes"], s["total_saved_bytes"])
        # hero atlas: dims halved, XML scaled, JSON scale compensated, on-screen size preserved
        self.assertEqual(Image.open(out / "images/characters/Hero.png").size, (1024, 1024))
        import xml.etree.ElementTree as ET
        old = list(ET.parse(self.src / "images/characters/Hero.xml").getroot().iter("SubTexture"))[1]
        new = list(ET.parse(out / "images/characters/Hero.xml").getroot().iter("SubTexture"))[1]
        new_scale = json.loads((out / "characters/hero.json").read_text())["scale"]
        self.assertAlmostEqual(int(new.get("frameWidth")) * new_scale, int(old.get("frameWidth")) * 1.2, delta=2.5)
        self.assertEqual(new.get("name"), old.get("name"))
        # untouched: Lua-referenced bg stays byte-identical (or lossless-only) and is reported as needing a manual fix
        self.assertEqual(Image.open(out / "images/stagebg.png").size, (2048, 2048))
        self.assertTrue(any(r["rel_path"].endswith("stagebg.png") and r.get("manual_fix_needed") for r in m["resize"]))
        self.assertEqual((out / "scripts/stage.lua").read_bytes(), (self.src / "scripts/stage.lua").read_bytes())
        self.assertEqual(s["json_files_rewritten"], s["optimized_resized"])

    def test_target_stops_early(self):
        m = self.run_mod(mode="balanced", allow_resize=True, scale=0.5, target_pct=1)
        self.assertLessEqual(m["summary"]["optimized_resized"], 1)
        m2 = self.run_mod(mode="balanced", allow_resize=True, scale=0.5, target_pct=99)
        self.assertGreater(m2["summary"]["optimized_resized"], m["summary"]["optimized_resized"])
        self.assertFalse(m2["summary"]["target_reached"])                              # target is a goal, not a promise

    def test_scale_limits_per_mode_and_never_upscale(self):
        m = self.run_mod(mode="balanced", allow_resize=True, scale=0.25, target_pct=99)
        self.assertEqual([r["dims_after"] for r in m["resize"] if r["status"] == "RESIZED"][0][0] in (1024,), True)  # clamped to 50%
        m = self.run_mod(mode="aggressive", allow_resize=True, scale=0.25, target_pct=99)
        self.assertIn(512, [r["dims_after"][0] for r in m["resize"] if r["status"] == "RESIZED"])
        m = self.run_mod(mode="balanced", allow_resize=True, scale=3.0, target_pct=99)
        for r in m["resize"]:
            if r["status"] == "RESIZED": self.assertLess(r["dims_after"][0], r["dims_before"][0])

    def test_dry_run_changes_nothing(self):
        before = self.tree(self.src)
        m = self.run_mod(mode="aggressive", allow_resize=True, target_pct=60)
        self.assertEqual(self.tree(self.src), before); self.assertEqual(m["summary"]["files_changed"], 0)
        self.assertGreater(m["summary"]["files_would_change"], 0)
        self.assertEqual(get_progress()["phase"], "done")
        self.assertFalse(list(self.ws.glob("tmp-*")))

    def test_cancel_and_existing_destination(self):
        ev = threading.Event(); ev.set(); out = self.t / "out"
        m = optimize_mod(self.src, self.ws, out, True, cancel=ev, settings=Settings(mode="balanced", allow_resize=True))
        self.assertEqual(m["status"], "CANCELLED"); self.assertFalse(out.exists()); self.assertFalse(list(self.ws.glob("tmp-*")))
        out.mkdir()
        with self.assertRaises(PathError): optimize_mod(self.src, self.ws, out, True)

    def test_bad_files_do_not_stop_the_run(self):
        (self.src / "images/zero.png").write_bytes(b""); (self.src / "images/junk.png").write_bytes(b"junk")
        m = self.run_mod(mode="lossless")
        self.assertEqual(m["summary"]["failed"], 2); self.assertEqual(m["status"], "WARNING")
        self.assertGreater(m["summary"]["lossless_saved_bytes"], 0)


class TestMath(unittest.TestCase):
    def test_reduction_pct(self):
        self.assertEqual(reduction_pct(0, 0), 0.0); self.assertEqual(reduction_pct(200, 100), 50.0)
        self.assertEqual(reduction_pct(100, 120), -20.0)       # a net increase is reported plainly

    def test_empty_folder(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "mod").mkdir()
            m = optimize_mod(Path(d) / "mod", Path(d) / "ws")
            self.assertEqual(m["summary"]["png_original_bytes"], 0); self.assertEqual(m["summary"]["total_reduction_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
