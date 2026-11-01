import io, json, os, random, shutil, sys, tempfile, unittest, zipfile
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "src", "main", "python"))
from PIL import Image
from funkerlitelab import engine


def make_atlas(name, W, H, fw, fh, n, dup=True, rotated=False, mode="RGBA", seed=5):
    """Animate-like sheet: frames have transparent margins; odd frames repeat the previous one."""
    random.seed(seed)
    im = Image.new("RGBA", (W, H))
    xml = ['<?xml version="1.0"?><TextureAtlas imagePath="%s.png">' % name]
    x = y = 0
    prev = None
    for i in range(n):
        if dup and prev is not None and i % 2 == 1:
            fr = prev
        else:
            fr = Image.new("RGBA", (fw, fh))
            px = fr.load()
            ox, oy = random.randint(40, 90), random.randint(40, 90)
            for yy in range(oy, fh - oy):
                for xx in range(ox, fw - ox):
                    px[xx, yy] = (random.randrange(256), random.randrange(256), 90, 255 if xx % 7 else 128)
        prev = fr
        if x + fw > W:
            x, y = 0, y + fh
        im.paste(fr, (x, y))
        xml.append('<SubTexture name="a%04d" x="%d" y="%d" width="%d" height="%d" frameX="-3" frameY="-2" '
                   'frameWidth="%d" frameHeight="%d"%s/>' % (i, x, y, fw, fh, fw + 6, fh + 4,
                                                           ' rotated="true"' if rotated else ""))
        x += fw
    xml.append("</TextureAtlas>")
    if mode == "RGB":
        im = im.convert("RGB")
    return im, "\n".join(xml)


def frames_rendered(png_bytes, xml_bytes):
    """Every frame composed onto its untrimmed canvas, keyed by name (premultiplied for comparison)."""
    im = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    out = {}
    for e in ET.fromstring(xml_bytes).iter("SubTexture"):
        g = lambda k, d=0: int(float(e.get(k, d)))
        x, y, w, h = g("x"), g("y"), g("width"), g("height")
        fx, fy = g("frameX"), g("frameY")
        fw, fh = g("frameWidth", w), g("frameHeight", h)
        canvas = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
        canvas.paste(im.crop((x, y, x + w, y + h)), (-fx, -fy))
        out[e.get("name")] = (fw, fh, canvas.convert("RGBa").tobytes())
    return out


class RepackBase(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.mod = os.path.join(self.t, "mod")
        self.out = os.path.join(self.t, "out")
        os.makedirs(self.out)

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def put(self, rel, data):
        p = os.path.join(self.mod, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if isinstance(data, Image.Image):
            data.save(p)
        else:
            open(p, "wb").write(data if isinstance(data, bytes) else data.encode())

    def atlas(self, rel, name=None, **kw):
        name = name or os.path.splitext(os.path.basename(rel))[0]
        im, xml = make_atlas(name, **kw)
        self.put(rel + ".png" if not rel.endswith(".png") else rel, im)
        self.put(os.path.splitext(rel)[0] + ".xml", xml)
        return im, xml

    def run_engine(self, s):
        z = os.path.join(self.out, s + ".zip")
        return z, engine.optimize_mod(self.mod, z, s)


class TestRepack(RepackBase):
    def test_rendering_identical_and_memory_smaller(self):
        im, xml = self.atlas("images/stages/prop.png", name="prop", W=2048, H=2048, fw=256, fh=256, n=56)
        self.put("scripts/s.lua", "makeAnimatedLuaSprite('p','stages/prop',0,0)")  # lua use must not block repack
        z, rep = self.run_engine("strong")
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["repacked"], 1)
        with zipfile.ZipFile(z) as zf:
            new_png, new_xml = zf.read("images/stages/prop.png"), zf.read("images/stages/prop.xml")
        old_png = open(os.path.join(self.mod, "images/stages/prop.png"), "rb").read()
        a, b = frames_rendered(old_png, xml.encode()), frames_rendered(new_png, new_xml)
        self.assertEqual(a.keys(), b.keys())
        for k in a:
            self.assertTrue(a[k] == b[k], "frame %s renders differently" % k)  # size + premultiplied pixels (no diff dump: it is huge)
        nw, nh = Image.open(io.BytesIO(new_png)).size
        self.assertLess(nw * nh, 0.5 * 2048 * 2048)
        self.assertLess(rep["texture_bytes_after"], rep["texture_bytes_before"])

    def test_scale_and_frame_sizes_untouched(self):
        self.atlas("images/characters/bfx.png", name="bfx", W=2048, H=2048, fw=256, fh=256, n=40)
        self.put("characters/bfx.json", json.dumps({"image": "characters/bfx", "scale": 1.5}))
        z, rep = self.run_engine("strong")
        with zipfile.ZipFile(z) as zf:
            if rep["resized"] == 0:
                self.assertEqual(json.loads(zf.read("characters/bfx.json"))["scale"], 1.5)
            for e in ET.fromstring(zf.read("images/characters/bfx.xml")).iter("SubTexture"):
                self.assertEqual((e.get("frameWidth"), e.get("frameHeight")), ("262", "260"))

    def test_identical_frames_share_one_rect(self):
        self.atlas("images/stages/prop.png", name="prop", W=2048, H=2048, fw=256, fh=256, n=40)
        z, _ = self.run_engine("maximum")
        with zipfile.ZipFile(z) as zf:
            rects = {(e.get("x"), e.get("y")) for e in ET.fromstring(zf.read("images/stages/prop.xml")).iter("SubTexture")}
        self.assertLess(len(rects), 40)
        self.assertLessEqual(len(rects), 20)

    def test_light_and_balanced_do_not_repack(self):
        self.atlas("images/stages/prop.png", name="prop", W=2048, H=2048, fw=256, fh=256, n=40)
        for s in ("light", "balanced"):
            z, rep = self.run_engine(s)
            self.assertEqual(rep["repacked"], 0)
            with zipfile.ZipFile(z) as zf:
                self.assertEqual(Image.open(io.BytesIO(zf.read("images/stages/prop.png"))).size, (2048, 2048))

    def test_rotated_atlas_left_alone(self):
        self.atlas("images/stages/rot.png", name="rot", W=1024, H=1024, fw=128, fh=128, n=20, rotated=True)
        z, rep = self.run_engine("maximum")
        self.assertEqual(rep["repacked"], 0)
        with zipfile.ZipFile(z) as zf:
            self.assertEqual(Image.open(io.BytesIO(zf.read("images/stages/rot.png"))).size, (1024, 1024))

    def test_opaque_image_left_alone(self):
        self.atlas("images/stages/opq.png", name="opq", W=1024, H=1024, fw=128, fh=128, n=20, mode="RGB")
        _, rep = self.run_engine("maximum")
        self.assertEqual(rep["repacked"], 0)

    def test_tightly_packed_atlas_not_repacked(self):
        # fully opaque frames filling the sheet: nothing to trim or merge
        im = Image.new("RGBA", (512, 512))
        random.seed(2)
        px = im.load()
        for y in range(512):
            for x in range(512):
                px[x, y] = (random.randrange(256), random.randrange(256), random.randrange(256), 255)
        xml = '<TextureAtlas imagePath="t.png">' + "".join(
            '<SubTexture name="f%d" x="%d" y="%d" width="256" height="256"/>' % (i, (i % 2) * 256, (i // 2) * 256)
            for i in range(4)) + "</TextureAtlas>"
        self.put("images/stages/t.png", im)
        self.put("images/stages/t.xml", xml)
        z, rep = self.run_engine("maximum")
        self.assertEqual(rep["repacked"], 0)
        self.assertTrue(rep["ok"])

    def test_repack_then_resize_when_still_too_big(self):
        # 3 distinct large frames: repacked sheet still > 1024 -> resized afterwards, refs updated
        self.atlas("images/characters/big.png", name="big", W=4096, H=2048, fw=1400, fh=1400, n=4, dup=False)
        self.put("characters/big.json", json.dumps({"image": "characters/big", "scale": 1}))
        z, rep = self.run_engine("maximum")
        self.assertTrue(rep["ok"], rep.get("problems"))
        with zipfile.ZipFile(z) as zf:
            im = Image.open(io.BytesIO(zf.read("images/characters/big.png")))
            js = json.loads(zf.read("characters/big.json"))
        if rep["resized"]:
            self.assertLessEqual(max(im.size), 1024)
            self.assertGreater(js["scale"], 1)
        self.assertLess(rep["texture_bytes_after"], rep["texture_bytes_before"])

    def test_report_has_measurements_and_duplicates(self):
        self.atlas("images/a/x.png", name="x", W=1024, H=1024, fw=128, fh=128, n=10)
        shutil.copy(os.path.join(self.mod, "images/a/x.png"), os.path.join(self.mod, "images/b_x.png"))
        _, rep = self.run_engine("light")
        self.assertEqual(rep["texture_bytes_before"], rep["texture_bytes_after"])  # lossless never changes RAM
        self.assertEqual(rep["duplicate_textures"]["groups"], 1)
        self.assertEqual(rep["duplicate_textures"]["decoded_bytes_wasted"], 1024 * 1024 * 4)
        self.assertTrue(rep["top_remaining_textures"])

    def test_original_untouched_by_repack(self):
        self.atlas("images/stages/prop.png", name="prop", W=2048, H=2048, fw=256, fh=256, n=40)
        import hashlib
        h = lambda: {f: hashlib.sha256(open(os.path.join(dp, f), "rb").read()).hexdigest()
                     for dp, _, fn in os.walk(self.mod) for f in fn}
        before = h()
        self.run_engine("maximum")
        self.assertEqual(before, h())


if __name__ == "__main__":
    unittest.main()
