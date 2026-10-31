"""Automatic per-image scale selection."""
import random, unittest
from PIL import Image
from funkerlitelab.operation import Settings, optimize_mod
from funkerlitelab.resize import alignment_error, choose_factor, detail_loss, _sample_tiles
from funkerlitelab.validate import validate_output
from test_stage2 import Fixture, art


class TestAuto(Fixture):
    def run_mod(self, **kw):
        return optimize_mod(self.src, self.ws, kw.pop("output", None), kw.pop("apply", False), settings=Settings(**kw))

    def test_default_is_auto(self):
        self.assertEqual(Settings().scale, "auto")

    def test_smooth_art_is_shrunk_and_choice_is_the_smallest_passing_factor(self):
        m = self.run_mod(mode="aggressive", allow_resize=True, target_pct=90)
        hero = [r for r in m["resize"] if r["rel_path"].endswith("Hero.png")][0]
        self.assertEqual(hero["status"], "RESIZED")
        rows = hero["auto"]["tested"]; chosen = [r for r in rows if "rejected" not in r][-1]
        self.assertEqual(chosen["factor"], hero["auto"]["chosen"])
        self.assertTrue(all("rejected" in r for r in rows[:-1]))            # every smaller factor was rejected for a reason
        self.assertLessEqual(chosen["loss"], hero["auto"]["loss_limit"])

    def test_detailed_image_is_refused_not_forced(self):
        rnd = random.Random(7)
        noise = Image.frombytes("RGBA", (2048, 1024), bytes(rnd.getrandbits(8) for _ in range(2048 * 1024 * 4)))
        noise.putalpha(255); noise.save(self.src / "images/characters/Villain.png", compress_level=1)
        m = self.run_mod(mode="balanced", allow_resize=True, target_pct=99)
        v = [r for r in m["resize"] if r["rel_path"].endswith("Villain.png")][0]
        self.assertEqual(v["status"], "SKIPPED"); self.assertIn("no safe factor", v["reason"]); self.assertIn("detail loss", v["reason"])
        self.assertEqual(m["summary"]["target_reached"], False)

    def test_auto_output_passes_validation_with_compensated_scale(self):
        out = self.t / "out"
        m = self.run_mod(mode="aggressive", allow_resize=True, target_pct=60, output=out, apply=True)
        self.assertIn(m["status"], ("SUCCESS", "WARNING"), m["errors"])
        v = validate_output(self.src, out)
        c = [c for c in v["checks"] if c["name"].startswith("resized atlases")][0]
        self.assertEqual(c["state"], "PASSED", c["files"])


class TestMeasures(unittest.TestCase):
    def test_alignment_error(self):
        x = '<SubTexture name="a" x="0" y="0" width="4" height="4"/>'
        self.assertEqual(alignment_error(x, 0.5, 0.5), 0.0)
        self.assertAlmostEqual(alignment_error('<SubTexture name="a" x="1" y="1" width="2" height="2"/>', 0.5, 0.5), 0.5)

    def test_detail_loss_is_higher_for_detailed_content(self):
        smooth = _sample_tiles(art(1024, 1024, 1)); rnd = random.Random(3)
        noisy = Image.frombytes("RGBA", (1024, 1024), bytes(rnd.getrandbits(8) for _ in range(1024 * 1024 * 4))); noisy.putalpha(255)
        self.assertLess(detail_loss(smooth, 0.5), detail_loss(_sample_tiles(noisy), 0.5))
        self.assertLess(detail_loss(smooth, 0.9), detail_loss(smooth, 0.25))   # more shrinking loses more


if __name__ == "__main__":
    unittest.main()
