"""Transactional optimize-to-new-copy operation. The source mod is never written.

Phase 1 (lossless): every PNG gets its best verified lossless candidate (stored on disk in the workspace,
not in RAM). Phase 2 (resize, only if the user enabled it and the target is not yet reached): the largest
compensable character atlases are downscaled until the target reduction is reached. Dry-run measures
everything but creates no output. Apply builds a hidden staging folder, verifies it, then renames it.
"""
import json
import os
import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from . import __version__
from .hashing import sha256_file
from .paths import validate_roots
from .png_optimizer import build_candidate
from .references import index_references
from .resize import MODE_LIMITS, build_resized

MANIFEST_SCHEMA = 2
MODES = ("lossless", "balanced", "aggressive")


@dataclass
class Settings:
    mode: str = "lossless"
    allow_resize: bool = False      # resizing happens only if this is True AND mode != lossless
    scale: float = 0.5
    target_pct: float = 45.0
    max_pixels: int = 70_000_000
    strip_metadata: bool = True

    @property
    def resize_active(self):
        return self.allow_resize and self.mode in ("balanced", "aggressive")


_progress = {"phase": "idle", "current": "", "done": 0, "total": 0, "saved_bytes": 0}
_plock = threading.Lock()


def get_progress():
    with _plock:
        return dict(_progress)


def _set_progress(**kw):
    with _plock:
        _progress.update(kw)


def reduction_pct(original, final):
    """100 x (original - final) / original, safe for original == 0."""
    return 0.0 if original <= 0 else 100.0 * (original - final) / original


def _walk_files(root):
    for dp, dn, fn in os.walk(root, followlinks=False):
        for n in fn:
            p = Path(dp) / n
            if not p.is_symlink():
                yield p


def optimize_mod(source, workspace, output=None, apply=False, cancel=None, max_pixels=None, settings=None):
    s = settings or Settings()
    if max_pixels is not None:
        s.max_pixels = max_pixels
    if s.mode not in MODES:
        raise ValueError(f"unknown mode {s.mode!r}")
    src, out, ws = validate_roots(source, output if apply else None, workspace)
    op_id = uuid.uuid4().hex[:12]
    ws.mkdir(parents=True, exist_ok=True)
    m = {"schema": MANIFEST_SCHEMA, "app_version": __version__, "operation_id": op_id,
         "mode": "apply" if apply else "dry-run", "started": time.time(), "source": str(src),
         "destination": str(out) if out else None, "workspace": str(ws),
         "settings": {**asdict(s), "resize_active": s.resize_active},
         "status": "RUNNING", "images": [], "resize": [], "warnings": [], "errors": []}
    mpath = ws / f"manifest-{op_id}.json"

    def save():
        tmp = mpath.with_suffix(".tmp")
        tmp.write_text(json.dumps(m, indent=2))
        os.replace(tmp, mpath)

    def cancelled():
        return cancel is not None and cancel.is_set()

    save()  # an interrupted run stays detectable: status remains RUNNING
    tmpdir, stage = ws / f"tmp-{op_id}", None
    _set_progress(phase="scanning", current="", done=0, total=0, saved_bytes=0)
    try:
        files = list(_walk_files(src))
        pngs = [p for p in files if p.suffix.lower() == ".png"]
        m["source_file_count"] = len(files)
        m["source_total_bytes"] = sum(p.stat().st_size for p in files)
        tmpdir.mkdir()
        # ---- phase 1: lossless
        plan = {}  # rel -> dict(orig, lossless, final, file, res, resize)
        _set_progress(phase="lossless", total=len(pngs))
        for i, p in enumerate(pngs):
            if cancelled():
                m["status"] = "CANCELLED"
                return _finish(m, save, stage, tmpdir)
            rel = p.relative_to(src).as_posix()
            _set_progress(current=rel, done=i)
            res, data = build_candidate(p, s.max_pixels, s.strip_metadata)
            res.rel_path = rel
            entry = {"res": res, "orig": res.original_size, "lossless": res.original_size,
                     "final": res.original_size, "file": None, "resize": None}
            if data is not None:
                f = tmpdir / f"L{i}.png"
                f.write_bytes(data)
                entry.update(lossless=len(data), final=len(data), file=f)
            plan[rel] = entry
        orig_total = sum(e["orig"] for e in plan.values())
        lossless_total = sum(e["lossless"] for e in plan.values())
        _set_progress(saved_bytes=orig_total - lossless_total)
        # ---- phase 2: user-approved resize, largest first, until the target is met
        xml_edits, json_edits = {}, {}
        m["target_pct"] = s.target_pct
        if s.resize_active and reduction_pct(orig_total, lossless_total) < s.target_pct:
            refs = index_references(src)
            cands = sorted((r for r, e in plan.items() if e["res"].status != "FAILED"),
                           key=lambda r: -plan[r]["lossless"])
            _set_progress(phase="resize", total=len(cands), done=0)
            current_total = lossless_total
            for i, rel in enumerate(cands):
                if reduction_pct(orig_total, current_total) >= s.target_pct:
                    break
                if cancelled():
                    m["status"] = "CANCELLED"
                    return _finish(m, save, stage, tmpdir)
                _set_progress(current=rel, done=i)
                info, rp = build_resized(src, rel, s.mode, s.scale, refs, s.strip_metadata, s.max_pixels)
                if rp is not None and len(rp["png_bytes"]) < plan[rel]["lossless"]:
                    f = tmpdir / f"R{i}.png"
                    f.write_bytes(rp["png_bytes"])
                    current_total -= plan[rel]["lossless"] - len(rp["png_bytes"])
                    plan[rel].update(final=len(rp["png_bytes"]), file=f, resize=info)
                    xml_edits[rp["xml_rel"]] = rp["xml_text"]
                    json_edits.update(rp["json_edits"])
                    info["bytes_after"] = len(rp["png_bytes"])
                    _set_progress(saved_bytes=orig_total - current_total)
                elif rp is not None:
                    info.update(status="SKIPPED", reason="resized file was not smaller than the lossless result")
                m["resize"].append(info)
        # ---- results
        for rel, e in plan.items():
            d = asdict(e["res"])
            d.update(bytes_saved=e["orig"] - e["final"], lossless_size=e["lossless"], planned_final_size=e["final"],
                     stage="resize" if e["resize"] else ("lossless" if e["file"] else "none"))
            if e["resize"]:
                d.update(dims_after=e["resize"]["dims_after"], resize_factor=e["resize"]["factor"])
            m["images"].append(d)
        changed_plan = [r for r, e in plan.items() if e["file"] is not None]
        # ---- apply
        if apply:
            _set_progress(phase="copying", current="", done=0, total=len(files))
            free = shutil.disk_usage(out.parent).free
            if free < m["source_total_bytes"] * 1.1:
                raise OSError(f"insufficient space: need ~{int(m['source_total_bytes']*1.1)}, free {free}")
            stage = out.parent / f".{out.name}.flab-tmp-{op_id}"
            stage.mkdir()
            m["staging"] = str(stage)
            save()
            src_hash = {}
            for i, p in enumerate(files):
                if cancelled():
                    m["status"] = "CANCELLED"
                    return _finish(m, save, stage, tmpdir)
                rel = p.relative_to(src).as_posix()
                src_hash[rel] = sha256_file(p)
                dest = stage / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, dest)
                _set_progress(current=rel, done=i + 1)
            for rel in changed_plan:
                os.replace(plan[rel]["file"], stage / rel)
                plan[rel]["res"].applied = True
            for rel, text in {**xml_edits, **json_edits}.items():
                (stage / rel).write_bytes(text.encode("utf-8"))
            touched = set(changed_plan) | set(xml_edits) | set(json_edits)
            for rel, h in src_hash.items():
                if rel not in touched and sha256_file(stage / rel) != h:
                    raise RuntimeError(f"unchanged file differs from source: {rel}")
            from PIL import Image  # final check on what is actually on disk
            for rel in changed_plan:
                with Image.open(stage / rel) as im:
                    im.load()
                    want = plan[rel]["resize"]["dims_after"] if plan[rel]["resize"] else list(plan[rel]["res"].dims_before)
                    if list(im.size) != list(want):
                        raise RuntimeError(f"output dimensions wrong for {rel}")
            disk_final = sum((stage / r).stat().st_size for r in plan)
            os.rename(stage, out)  # commit
            stage = None
            m["disk_verified_png_final_bytes"] = disk_final
            for d in m["images"]:
                d["applied"] = d["stage"] != "none"
        final_total = sum(e["final"] for e in plan.values())
        if apply and m["disk_verified_png_final_bytes"] != final_total:
            m["warnings"].append("planned and on-disk PNG totals differ")
        imgs = m["images"]
        resized = [r for r in m["resize"] if r["status"] == "RESIZED" and plan[r["rel_path"]]["resize"]]
        m["summary"] = {
            "png_examined": len(imgs),
            "files_changed": len(changed_plan) if apply else 0,
            "files_would_change": len(changed_plan),
            "optimized_lossless": sum(1 for d in imgs if d["stage"] == "lossless"),
            "optimized_resized": sum(1 for d in imgs if d["stage"] == "resize"),
            "unchanged": sum(1 for d in imgs if d["stage"] == "none" and "not strictly smaller" in d["reason"]),
            "failed": sum(d["status"] == "FAILED" for d in imgs),
            "skipped": sum(d["status"] == "SKIPPED" and d["stage"] == "none" and "not strictly smaller" not in d["reason"] for d in imgs),
            "png_original_bytes": orig_total,
            "png_after_lossless_bytes": lossless_total,
            "png_final_bytes": final_total,
            "lossless_saved_bytes": orig_total - lossless_total,
            "resize_saved_bytes": lossless_total - final_total,
            "total_saved_bytes": orig_total - final_total,
            "lossless_reduction_pct": reduction_pct(orig_total, lossless_total),
            "total_reduction_pct": reduction_pct(orig_total, final_total),
            "target_pct": s.target_pct,
            "target_reached": reduction_pct(orig_total, final_total) >= s.target_pct if orig_total else False,
            "resize_blocked_needs_manual_fix": sum(1 for r in m["resize"] if r.get("manual_fix_needed")),
            "xml_files_rewritten": len(xml_edits), "json_files_rewritten": len(json_edits),
            "dry_run_potential_bytes": orig_total - final_total,
        }
        m["status"] = "SUCCESS" if not m["summary"]["failed"] else "WARNING"
        return _finish(m, save, stage, tmpdir)
    except Exception as e:
        m["status"] = "FAILED"
        m["errors"].append(f"{type(e).__name__}: {e}")
        return _finish(m, save, stage, tmpdir)


def _finish(m, save, stage, tmpdir):
    for d, key in ((stage, "staging_cleaned"), (tmpdir, "tmp_cleaned")):
        if d is not None and d.exists():
            shutil.rmtree(d)  # both folders were created by this operation
            m[key] = True
    m["finished"] = time.time()
    _set_progress(phase="done" if m["status"] in ("SUCCESS", "WARNING") else m["status"].lower(), current="")
    save()
    return m
