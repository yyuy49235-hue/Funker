"""Shareable diagnostic report built from a manifest. Contains no file contents, no tokens, no absolute paths."""
import json
import platform
import sys
import traceback
from pathlib import Path

from . import __version__


def sanitize(text, replacements):
    for real, label in replacements:
        if real:
            text = text.replace(str(real), label)
    return text


def failure_record(ctx, exc, replacements):
    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    tail = sanitize("".join(tb[-6:]), replacements)
    return {"stage": ctx.get("stage"), "file": ctx.get("file"), "exception": type(exc).__name__,
            "message": sanitize(str(exc), replacements), "traceback_tail": tail}


def environment():
    info = {"app_version": __version__, "python": sys.version.split()[0], "platform": sys.platform}
    try:
        import PIL
        info["pillow"] = PIL.__version__
    except ImportError:
        info["pillow"] = None
    try:
        import numpy
        info["numpy"] = numpy.__version__
    except ImportError:
        info["numpy"] = None
    return info


def build_report(m):
    """m = manifest dict. Absolute folders are replaced by <SRC>/<OUT>/<WORKSPACE>."""
    rep = [(m.get("staging"), "<STAGING>"), (m.get("destination"), "<OUT>"), (m.get("source"), "<SRC>"),
           (m.get("workspace"), "<WORKSPACE>")]
    s = m.get("summary") or {}
    imgs = m.get("images", [])
    problems = [{"file": i["rel_path"], "status": i["status"], "reason": sanitize(i["reason"], rep)}
                for i in imgs if i["status"] == "FAILED"][:50]
    skipped = [{"file": r["rel_path"], "reason": sanitize(r["reason"], rep)} for r in m.get("resize", [])
               if r["status"] in ("SKIPPED", "FAILED")][:50]
    return {
        "run_id": m.get("operation_id"), "app_version": m.get("app_version"), "status": m.get("status"),
        "mode": m.get("mode"), "settings": m.get("settings"), "environment": environment(),
        "source": "<SRC>", "destination": "<OUT>" if m.get("destination") else None,
        "counts": {"files_discovered": m.get("source_file_count"), "png_examined": s.get("png_examined"),
                   "optimized_lossless": s.get("optimized_lossless"), "optimized_resized": s.get("optimized_resized"),
                   "unchanged": s.get("unchanged"), "skipped": s.get("skipped"), "failed": s.get("failed")},
        "bytes": {"png_original": s.get("png_original_bytes"), "png_final": s.get("png_final_bytes"),
                  "total_reduction_pct": s.get("total_reduction_pct")},
        "failure": ({**m["failure"]} if m.get("failure") else None),
        "errors": [sanitize(e, rep) for e in m.get("errors", [])],
        "warnings": [sanitize(w, rep) for w in m.get("warnings", [])],
        "validation": m.get("validation"), "failed_images": problems, "resize_skipped": skipped,
        "note": "No file contents, tokens or absolute paths are included.",
    }


def render_text(report):
    return json.dumps(report, indent=2, ensure_ascii=False)
