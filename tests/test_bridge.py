import json, tempfile, unittest, threading
from pathlib import Path
from PIL import Image
import bridge


class TestBridge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.t = Path(self.tmp.name)
        self.mod = self.t / "mod"; (self.mod / "images").mkdir(parents=True)
        Image.new("RGBA", (64, 64), (5, 6, 7, 8)).save(self.mod / "images" / "a.png", compress_level=0)
        (self.mod / "images" / "a.xml").write_text('<TextureAtlas imagePath="a.png"><SubTexture name="f" x="0" y="0" width="8" height="8"/></TextureAtlas>')
        self.ws = str(self.t / "ws")
    def tearDown(self): self.tmp.cleanup()
    def call(self, cmd, out="", lang="en", opts=None):
        return json.loads(bridge.run(cmd, str(self.mod), out, self.ws, lang, json.dumps(opts or {})))

    def test_scan_and_atlas(self):
        r = self.call("scan"); self.assertTrue(r["ok"]); self.assertIn("Files: 2", r["text"])
        r = self.call("atlas", lang="ar"); self.assertTrue(r["ok"]); self.assertIn("OK: 1", r["text"])

    def test_dry_changes_nothing_and_says_so(self):
        before = (self.mod / "images" / "a.png").read_bytes()
        r = self.call("dry", lang="ar")
        self.assertTrue(r["ok"]); self.assertIn("لم يتغير", r["text"])
        self.assertEqual((self.mod / "images" / "a.png").read_bytes(), before)

    def test_apply_creates_new_copy_and_refuses_existing(self):
        out = str(self.t / "out")
        r = self.call("apply", out); self.assertTrue(r["ok"], r["text"]); self.assertIn("original mod was not changed", r["text"])
        self.assertLess((self.t / "out/images/a.png").stat().st_size, (self.mod / "images/a.png").stat().st_size)
        r = self.call("apply", out); self.assertFalse(r["ok"]); self.assertIn("Path problem", r["text"])

    def test_cancelled_before_start_is_cleared_each_run(self):
        bridge.cancel()                     # a stale cancel must not poison the next run
        self.assertTrue(self.call("dry")["ok"])

    def test_options_reach_engine_and_report_splits_savings(self):
        r = self.call("dry", opts={"mode": "balanced", "allow_resize": False, "target_pct": 100})
        self.assertTrue(r["ok"]); self.assertIn("from lossless compression", r["text"]); self.assertIn("target NOT reached", r["text"])
        self.assertNotIn("+ resize", r["text"])           # resize needs the explicit flag
        r = self.call("dry", lang="ar", opts={"mode": "aggressive", "allow_resize": True})
        self.assertIn("resize", r["text"])

    def test_progress_json(self):
        self.call("dry"); p = json.loads(bridge.progress())
        self.assertEqual(p["phase"], "done"); self.assertIn("current", p)

    def test_unknown_and_missing(self):
        self.assertFalse(self.call("nope")["ok"])
        for c in ("scan", "atlas"):
            r = json.loads(bridge.run(c, str(self.t / "missing"), "", self.ws, "en"))
            self.assertFalse(r["ok"]); self.assertIn("Path problem", r["text"])


if __name__ == "__main__":
    unittest.main()
