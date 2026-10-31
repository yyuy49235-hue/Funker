"""v5: encoding preservation, failure context, diagnostics, validation, graph, inspect, adapters, exclude."""
import io, json, shutil, tempfile, unittest, contextlib
from pathlib import Path
from PIL import Image
from funkerlitelab import operation
from funkerlitelab.adapters import detect_atlas
from funkerlitelab.atlas_scale import ScaleError, decode_keep, encode_keep, scale_sparrow_xml
from funkerlitelab.cli import main as cli_main
from funkerlitelab.depgraph import build_graph
from funkerlitelab.diagnostics import build_report
from funkerlitelab.inspect_mod import inspect_mod
from funkerlitelab.operation import Settings, optimize_mod
from funkerlitelab.validate import FAILED, INCONCLUSIVE, NOT_TESTED, PASSED, WARNING, validate_output
from test_stage2 import Fixture, atlas_xml, CHAR_JSON


class TestEncoding(unittest.TestCase):
    def test_latin1_declared_atlas_is_written_back_as_latin1(self):  # v4 always wrote UTF-8
        raw = ('<?xml version="1.0" encoding="ISO-8859-1"?>\n<TextureAtlas imagePath="a.png"><SubTexture name="caf\xe9" '
               'x="0" y="0" width="4" height="4"/></TextureAtlas>').encode("latin-1")
        text, how = decode_keep(raw, True)
        new, _ = scale_sparrow_xml(text, .5, .5, 2, 2)
        out = encode_keep(new, how)
        self.assertIn("café".encode("latin-1"), out); self.assertNotIn("café".encode("utf-8"), out)

    def test_bom_preserved_and_bad_encoding_refused(self):
        text, how = decode_keep(b"\xef\xbb\xbf{}", False)
        self.assertEqual(encode_keep(text, how), b"\xef\xbb\xbf{}")
        with self.assertRaises(ScaleError): decode_keep(b'<?xml version="1.0" encoding="utf-8"?>\xff\xfe<a/>', True)


class TestAdapters(unittest.TestCase):
    def test_other_atlas_formats_recognized_but_not_modifiable(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); (d / "images").mkdir()
            for n in ("p", "j", "a"): Image.new("RGBA", (4, 4)).save(d / "images" / f"{n}.png")
            (d / "images/p.txt").write_text("frame1 = 0 0 2 2\nframe2 = 2 0 2 2\n")
            (d / "images/j.json").write_text('{"frames": {}, "meta": {}}')
            (d / "images/a").mkdir(); (d / "images/a/Animation.json").write_text("{}")
            for n, want in (("p", "packer-txt"), ("j", "json-atlas"), ("a", "animate-atlas")):
                ad, _ = detect_atlas(d, f"images/{n}.png"); self.assertEqual(ad.name, want); self.assertFalse(ad.can_scale)


class V5(Fixture):
    def run_mod(self, **kw):
        return optimize_mod(self.src, self.ws, kw.pop("output", None), kw.pop("apply", False), settings=Settings(**kw))

    def good_output(self):
        out = self.t / "out"
        m = self.run_mod(mode="aggressive", allow_resize=True, scale=0.5, target_pct=40, output=out, apply=True)
        self.assertIn(m["status"], ("SUCCESS", "WARNING"), m["errors"]); return out, m


class TestFailureContext(V5):
    def test_error_names_stage_and_file_and_report_has_no_absolute_paths(self):
        real = operation.build_candidate
        def boom(path, *a, **k):
            if path.name == "Hero.png": raise RuntimeError(f"cannot read {path}")
            return real(path, *a, **k)
        operation.build_candidate = boom
        try:
            m = self.run_mod(mode="lossless")
        finally:
            operation.build_candidate = real
        self.assertEqual(m["status"], "FAILED")
        self.assertEqual((m["failure"]["stage"], m["failure"]["file"]), ("lossless", "images/characters/Hero.png"))
        text = json.dumps(build_report(m))
        self.assertNotIn(str(self.t), text); self.assertIn("<SRC>", text)
        self.assertIn("lossless / images/characters/Hero.png", m["errors"][0])
        self.assertFalse(list(self.ws.glob("tmp-*")))

    def test_failure_leaves_no_output_folder(self):
        out = self.t / "out"; real = operation.validate_output
        operation.validate_output = lambda *a, **k: {"static": FAILED, "structural": PASSED, "checks": [
            {"name": "fake", "state": FAILED, "detail": "forced", "files": ["images/x.png"]}]}
        try:
            m = self.run_mod(mode="lossless", output=out, apply=True)
        finally:
            operation.validate_output = real
        self.assertEqual(m["status"], "FAILED"); self.assertFalse(out.exists())
        self.assertEqual(m["failure"]["stage"], "validation"); self.assertEqual(m["failure"]["file"], "images/x.png")
        self.assertFalse([p for p in self.t.iterdir() if "flab-tmp" in p.name])


class TestExclude(V5):
    def test_excluded_file_is_untouched_and_recorded(self):
        out = self.t / "out"
        m = self.run_mod(mode="lossless", exclude=["images/flat.png"], output=out, apply=True)
        self.assertEqual((out / "images/flat.png").read_bytes(), (self.src / "images/flat.png").read_bytes())
        d = [i for i in m["images"] if i["rel_path"] == "images/flat.png"][0]
        self.assertIn("excluded", d["reason"])


class TestValidation(V5):
    def state(self, v, prefix):
        return [c["state"] for c in v["checks"] if c["name"].startswith(prefix)][0]

    def test_good_output_passes_and_engine_tests_are_not_claimed(self):
        out, m = self.good_output()
        v = validate_output(self.src, out)
        self.assertEqual(v["static"] in (PASSED, WARNING), True, [c for c in v["checks"] if c["state"] == FAILED])
        self.assertEqual(self.state(v, "real engine"), NOT_TESTED); self.assertEqual(self.state(v, "manual"), NOT_TESTED)
        self.assertEqual(m["validation"]["engine_test"], NOT_TESTED)

    def test_missing_file_and_unexpected_change_detected(self):
        out, _ = self.good_output()
        (out / "scripts/stage.lua").write_text("changed"); (out / "images/flat.png").unlink()
        v = validate_output(self.src, out, expected_changes=set())
        self.assertEqual(self.state(v, "structure"), FAILED); self.assertEqual(self.state(v, "untouched"), FAILED)
        self.assertEqual(v["structural"], FAILED)

    def test_uncompensated_resize_is_caught(self):   # the failure class of the legacy pipeline
        out, _ = self.good_output()
        j = out / "characters/hero.json"; j.write_text(CHAR_JSON % ("Hero", "1.2"))   # scale put back to the original
        v = validate_output(self.src, out)
        c = [c for c in v["checks"] if c["name"].startswith("resized atlases")][0]
        self.assertEqual(c["state"], FAILED); self.assertIn("does not compensate", c["files"][0])

    def test_unscaled_xml_is_caught(self):
        out, _ = self.good_output()
        shutil.copy(self.src / "images/characters/Hero.xml", out / "images/characters/Hero.xml")
        v = validate_output(self.src, out)
        self.assertEqual(v["static"], FAILED)
        self.assertEqual(self.state(v, "atlas frames"), FAILED)

    def test_new_broken_reference_is_caught(self):
        out, _ = self.good_output()
        (out / "images/characters/Villain.png").unlink()
        v = validate_output(self.src, out)
        self.assertEqual(self.state(v, "known references"), FAILED)

    def test_cli_validate(self):
        out, _ = self.good_output(); buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli_main(["--config", str(self.t / "n.json"), "validate", str(self.src), str(out)])
        self.assertIn("ready_for_manual_test", json.loads(buf.getvalue()))


class TestGraphAndInspect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = Path(self.tmp.name)
        for sub in ("images/characters", "characters", "scripts", "stages", "weeks"): (self.d / sub).mkdir(parents=True)
        for n in ("Hero", "bg", "ghost", "spark"): Image.new("RGBA", (8, 8)).save(self.d / "images" / (("characters/" if n == "Hero" else "") + n + ".png"))
        (self.d / "images/characters/Hero.xml").write_text(atlas_xml("Hero.png", 8, 8, 2, False))
        (self.d / "characters/hero.json").write_text(CHAR_JSON % ("Hero", "1"))
        (self.d / "stages/s.json").write_text('{"directory": "", "defaultZoom": 0.9, "boyfriend": [0,0], "girlfriend": [0,0], "opponent": [0,0]}')
        (self.d / "scripts/a.lua").write_text("makeLuaSprite('b','bg',0,0)\nmakeLuaSprite('c', 'miss', 0, 0)\nlocal n = 'sp'\nmakeLuaSprite('d', n .. 'ark', 0, 0)\n-- ghost?\nx='ghost'\n")
    def tearDown(self): self.tmp.cleanup()

    def test_edges_have_honest_confidence(self):
        g = build_graph(self.d)
        by = {(e["from"], e["to"]): e for e in g["edges"]}
        self.assertEqual(by[("images/characters/Hero.xml", "images/characters/Hero.png")]["confidence"], "confirmed")
        self.assertEqual(by[("characters/hero.json", "images/characters/Hero.png")]["confidence"], "confirmed")
        self.assertEqual(by[("scripts/a.lua", "images/bg.png")]["confidence"], "confirmed")
        self.assertEqual(by[("scripts/a.lua", "images/miss.png")]["confidence"], "unresolved")
        self.assertEqual(by[("scripts/a.lua", "images/ghost.png")]["confidence"], "inferred")
        self.assertEqual(len(g["dynamic_references"]), 1)
        self.assertIn("images/spark.png", g["images_without_static_reference"])   # listed, not called 'unused'
        self.assertIn("not mean unused", g["limits"])

    def test_inspect_states_confidence_and_unknown_version(self):
        i = inspect_mod(self.d)
        self.assertIn(i["engine_guess"]["confidence"], ("medium", "high", "low"))
        self.assertIn("unknown", i["engine_guess"]["version"]); self.assertTrue(i["has_lua"])
        self.assertEqual(i["png_atlas_formats"]["sparrow-xml"], 1)


class TestMenuCharacterJson(unittest.TestCase):
    def test_menu_character_image_resolves_under_menucharacters(self):   # found on the real Agoti mod
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); (d / "characters").mkdir(); (d / "images/menucharacters").mkdir(parents=True)
            Image.new("RGBA", (4, 4)).save(d / "images/menucharacters/agotiMenu.png")
            (d / "characters/agotiMenu.json").write_text('{"image": "agotiMenu", "scale": 0.9, "position": [0, 0], "idle_anim": "x", "confirm_anim": "y"}')
            e = [e for e in build_graph(d)["edges"] if e["from"] == "characters/agotiMenu.json"][0]
            self.assertEqual((e["confidence"], e["to"]), ("confirmed", "images/menucharacters/agotiMenu.png"))


class TestImagePathMismatch(V5):
    def test_exporter_name_in_imagePath_is_a_warning_not_a_blocker(self):   # real Agoti atlas: "Alt Agoti Sprites_B.png"
        x = self.src / "images/characters/Hero.xml"
        x.write_text(x.read_text().replace('imagePath="Hero.png"', 'imagePath="Hero Sheet.png"'))
        m = self.run_mod(mode="aggressive", allow_resize=True, target_pct=99)
        hero = [r for r in m["resize"] if r["rel_path"].endswith("Hero.png")][0]
        self.assertEqual(hero["status"], "RESIZED"); self.assertTrue(hero["warnings"])


class TestScaleScriptBlocker(V5):
    def test_script_that_scales_character_blocks_resize(self):
        (self.src / "scripts/char.lua").write_text("setProperty('dad.scale.x', 2)\n")
        m = self.run_mod(mode="aggressive", allow_resize=True, target_pct=60)
        self.assertEqual(m["summary"]["optimized_resized"], 0)
        self.assertTrue(any("alter character scale" in r["reason"] for r in m["resize"]))


if __name__ == "__main__":
    unittest.main()
