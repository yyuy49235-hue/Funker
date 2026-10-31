import hashlib, json, os, random, shutil, sys, tempfile, unittest, zipfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "src", "main", "python"))
from PIL import Image
from funkerlitelab import engine

XML = ('<?xml version="1.0"?><TextureAtlas imagePath="bf.png">'
       '<SubTexture name="idle0000" x="0" y="0" width="400" height="300" frameX="-10" frameY="-6" frameWidth="420" frameHeight="310"/>'
       '<SubTexture name="idle0001" x="1200" y="600" width="800" height="400"/></TextureAtlas>')


def noisy(w, h, seed=1):
    random.seed(seed)
    im = Image.new("RGBA", (w, h))
    px = im.load()
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            c = (random.randrange(256), random.randrange(256), random.randrange(256), 255 if (x // 400 + y // 300) % 2 else 0)
            for dy in range(4):
                for dx in range(4):
                    if x + dx < w and y + dy < h:
                        px[x + dx, y + dy] = c
    return im


def tree_hash(root):
    h = {}
    for dp, _, fn in os.walk(root):
        for f in fn:
            p = os.path.join(dp, f)
            h[os.path.relpath(p, root)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    return h


class Base(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.mod = os.path.join(self.t, "mod")
        self.out = os.path.join(self.t, "out")
        os.makedirs(self.out)
        self.w(  "images/characters/bf.png", None)
        noisy(2400, 1200).save(os.path.join(self.mod, "images/characters/bf.png"))
        self.w("images/characters/bf.xml", XML.encode())
        self.w("characters/bf.json", json.dumps({"image": "characters/bf", "scale": 1}).encode())
        # same-named folders in different places
        self.w("songs/a/data/chart.json", b'{"x":1}')
        self.w("weeks/a/data/chart.json", b'{"x":2}')
        self.w("music/inst.ogg", b"OggS-not-really")
        os.makedirs(os.path.join(self.mod, "empty_dir"))
        self.before = tree_hash(self.mod)

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def w(self, rel, data):
        p = os.path.join(self.mod, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if data is not None:
            open(p, "wb").write(data)

    def run_engine(self, strength):
        z = os.path.join(self.out, strength + ".zip")
        rep = engine.optimize_mod(self.mod, z, strength)
        return z, rep


class TestEngine(Base):
    def test_light_keeps_dimensions(self):
        z, rep = self.run_engine("light")
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["resized"], 0)
        with zipfile.ZipFile(z) as zf:
            zf.extract("images/characters/bf.png", self.t)
        self.assertEqual(Image.open(os.path.join(self.t, "images/characters/bf.png")).size, (2400, 1200))

    def test_balanced_resizes_and_updates_refs(self):
        z, rep = self.run_engine("balanced")
        self.assertEqual(rep["resized"], 1, rep["details"])
        with zipfile.ZipFile(z) as zf:
            im = Image.open(zf.open("images/characters/bf.png")); im.load()
            self.assertEqual(max(im.size), 2048)
            self.assertEqual(im.mode, "RGBA")
            self.assertEqual(im.size[0] / im.size[1], 2.0 if abs(im.size[0] / im.size[1] - 2.0) < 0.01 else None)
            self.assertIn(0, [im.getpixel((x, 5))[3] for x in range(0, im.size[0], 8)])  # transparency kept
            xml = zf.read("images/characters/bf.xml").decode()
            js = json.loads(zf.read("characters/bf.json"))
        f = im.size[0] / 2400.0
        self.assertAlmostEqual(js["scale"], 1 / f, places=2)
        self.assertIn('width="%d"' % round(400 * f), xml)
        self.assertIn('x="%d"' % round(1200 * f), xml)

    def test_strength_changes_output(self):
        _, b = self.run_engine("balanced")
        _, m = self.run_engine("maximum")
        self.assertLess(m["bytes_after"], b["bytes_after"])

    def test_original_untouched(self):
        for s in engine.LEVELS:
            self.run_engine(s)
        self.assertEqual(tree_hash(self.mod), self.before)

    def test_same_named_folders_not_merged_and_all_files_present(self):
        z, rep = self.run_engine("strong")
        with zipfile.ZipFile(z) as zf:
            names = set(zf.namelist())
            self.assertEqual(zf.read("songs/a/data/chart.json"), b'{"x":1}')
            self.assertEqual(zf.read("weeks/a/data/chart.json"), b'{"x":2}')
        for rel in self.before:
            self.assertIn(rel.replace(os.sep, "/"), names)
        self.assertIn("empty_dir/", names)
        self.assertEqual(rep["files_total"], len(self.before))

    def test_lua_reference_blocks_resize(self):
        self.w("scripts/x.lua", b"makeLuaSprite('s','characters/bf',0,0)")
        z, rep = self.run_engine("maximum")
        self.assertEqual(rep["resized"], 0)
        self.assertTrue(any("referenced by scripts/x.lua" in d["note"] for d in rep["details"]))
        with zipfile.ZipFile(z) as zf:
            self.assertEqual(json.loads(zf.read("characters/bf.json"))["scale"], 1)

    def test_no_character_json_blocks_resize(self):
        os.remove(os.path.join(self.mod, "characters/bf.json"))
        _, rep = self.run_engine("maximum")
        self.assertEqual(rep["resized"], 0)

    def test_corrupt_png_is_kept_and_reported(self):
        self.w("images/bad.png", b"\x89PNG garbage")
        z, rep = self.run_engine("light")
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["failed"], 1)
        with zipfile.ZipFile(z) as zf:
            self.assertEqual(zf.read("images/bad.png"), b"\x89PNG garbage")

    def test_lossless_is_pixel_identical(self):
        im = Image.new("RGBA", (300, 300), (10, 20, 30, 0))
        im.save(os.path.join(self.mod, "images/flat.png"), compress_level=0)
        z, rep = self.run_engine("light")
        with zipfile.ZipFile(z) as zf:
            out = Image.open(zf.open("images/flat.png")); out.load()
        self.assertEqual(list(out.getdata()), list(im.getdata()))
        self.assertGreaterEqual(rep["optimized"], 1)

    def test_output_inside_input_rejected(self):
        with self.assertRaises(ValueError):
            engine.optimize_mod(self.mod, os.path.join(self.mod, "o.zip"), "light")
        self.assertEqual(tree_hash(self.mod), self.before)

    def test_cancel_leaves_no_output(self):
        def cb(stage, d, t, n):
            raise engine.Cancelled()
        z = os.path.join(self.out, "c.zip")
        with self.assertRaises(engine.Cancelled):
            engine.optimize_mod(self.mod, z, "light", cb)
        self.assertFalse(os.path.exists(z))
        self.assertEqual(os.listdir(self.out), [])

    def test_bad_strength(self):
        with self.assertRaises(ValueError):
            engine.optimize_mod(self.mod, os.path.join(self.out, "x.zip"), "ultra")


if __name__ == "__main__":
    unittest.main()
