import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "src", "main", "python"))
import bridge


class Sink:
    def __init__(self, stop_at=None):
        self.calls, self.stop_at = [], stop_at

    def update(self, stage, done, total, name):
        self.calls.append(stage)
        return stage != self.stop_at


class TestBridge(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.t, "m"))
        open(os.path.join(self.t, "m", "a.txt"), "w").write("hi")

    def test_ok_and_progress(self):
        s = Sink()
        r = json.loads(bridge.run(os.path.join(self.t, "m"), os.path.join(self.t, "o.zip"), "light", s))
        self.assertTrue(r["ok"])
        self.assertIn("Packaging", s.calls)

    def test_cancel(self):
        r = json.loads(bridge.run(os.path.join(self.t, "m"), os.path.join(self.t, "o.zip"), "light", Sink("Packaging")))
        self.assertFalse(r["ok"]); self.assertTrue(r["cancelled"])

    def test_error_is_reported_not_raised(self):
        r = json.loads(bridge.run("/nonexistent", os.path.join(self.t, "o.zip"), "light", Sink()))
        self.assertFalse(r["ok"]); self.assertIn("error", r)


if __name__ == "__main__":
    unittest.main()
