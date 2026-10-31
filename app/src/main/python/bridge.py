import json

from funkerlitelab import engine


def run(input_dir, out_zip, strength, sink):
    def cb(stage, done, total, name):
        if not sink.update(stage, int(done), int(total), name):
            raise engine.Cancelled()

    try:
        return json.dumps(engine.optimize_mod(input_dir, out_zip, strength, cb))
    except engine.Cancelled:
        return json.dumps({"ok": False, "cancelled": True, "error": "Cancelled"})
    except Exception as e:
        return json.dumps({"ok": False, "error": "%s: %s" % (type(e).__name__, e)})
