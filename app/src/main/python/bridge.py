"""Thin layer between the Android UI (Kotlin) and the engine. Returns JSON text.
All real work lives in funkerlitelab/; nothing here decides safety."""
import json
import threading
from pathlib import Path

from funkerlitelab.atlas import check_atlases
from funkerlitelab.operation import Settings, get_progress, optimize_mod
from funkerlitelab.paths import PathError, validate_roots
from funkerlitelab.scanner import scan, summarize

_cancel = threading.Event()

T = {
    "ar": {
        "scan": "عدد الملفات: {files}\nالحجم الكلي: {size}\nملفات JSON/XML فيها أخطاء: {bad}\nملفات نوعها غير معروف: {unk}\n\nأكبر الملفات:",
        "atlas": "عدد ملفات XML: {n}\n{counts}\n\nالملفات اللي محتاجة مراجعة (مش معناها إن في عطل):",
        "atlas_ok": "كل الملفات سليمة من ناحية الأبعاد. ده مش ضمان إنها تشتغل في اللعبة.",
        "opt": "الوضع: {mode}\nحجم صور PNG قبل: {orig}\nحجم صور PNG بعد: {final}\nنسبة التقليل الكلية: {pct}\n- من الضغط بدون فقد: {ll} ({llpct})\n- من تصغير الأبعاد: {rs}\nالهدف: {target}% ← {reached}\nاتحسنت بدون فقد: {nl} | اتصغّرت: {nr} | من غير تغيير: {un} | اتخطّت: {sk} | فشلت: {fail}",
        "reached": "تم الوصول للهدف", "not_reached": "لم يتم الوصول للهدف (الهدف مش مضمون)",
        "blocked": "صور كبيرة ماتصغّرتش لأن الـ scale بتاعها لازم يتعدّل يدويًا: {n}",
        "dry_head": "تجربة فقط. لم يتغير أي ملف.", "size_only": "ده حجم الملفات على الجهاز بس، مش الرامات ولا الـ FPS.",
        "resized_warn": "الصور المصغّرة: اتعدّل ملف XML والـ scale في JSON الشخصية. لازم تجرّبها في اللعبة، لسه ماتجرّبتش.",
        "created": "تم إنشاء نسخة جديدة:\n{dest}\nالمود الأصلي لم يتغير.", "disk": "تم التأكد من الأحجام من الملفات الفعلية على الجهاز.",
        "why": "السبب: {r}",
        "dry": "تجربة فقط. لم يتغير أي ملف.\nصور PNG تم فحصها: {n}\nممكن تتصغّر بأمان: {ok}\nتم تخطيها: {skip}\nفشل فحصها: {fail}\nالتوفير المتوقع: {saved} (من {orig})\nده حجم الملفات على الجهاز بس، مش الرامات ولا الـ FPS.\n\nأكبر توفير:",
        "apply_ok": "تم إنشاء نسخة جديدة:\n{dest}\nالمود الأصلي لم يتغير.\nصور PNG تم فحصها: {n}\nصور تغيرت: {chg}\nتم تخطيها: {skip}\nفشلت: {fail}\nقبل: {orig}\nبعد: {final}\nالتوفير: {saved}\nلم يتم تجربتها في اللعبة بعد.",
        "failed": "فشلت العملية. لم يتم إنشاء أي مجلد والمود الأصلي سليم.\nالسبب: {why}",
        "cancelled": "تم الإلغاء. لم يتم إنشاء أي مجلد والمود الأصلي سليم.",
        "path": "مشكلة في المسار: {why}",
        "error": "خطأ غير متوقع: {why}",
        "manifest": "سجل العملية: {p}",
        "partial": "تنبيه: الفحص اتلغى والنتيجة ناقصة.",
        "unknown": "أمر غير معروف: {c}",
    },
    "en": {
        "scan": "Files: {files}\nTotal size: {size}\nJSON/XML files with errors: {bad}\nUnknown-type files: {unk}\n\nLargest files:",
        "atlas": "XML files: {n}\n{counts}\n\nFiles to review (not necessarily broken):",
        "atlas_ok": "All atlases fit their images. This does not guarantee they work in game.",
        "opt": "Mode: {mode}\nPNG size before: {orig}\nPNG size after: {final}\nTotal reduction: {pct}\n- from lossless compression: {ll} ({llpct})\n- from resizing: {rs}\nTarget: {target}% -> {reached}\nLossless-optimized: {nl} | resized: {nr} | unchanged: {un} | skipped: {sk} | failed: {fail}",
        "reached": "target reached", "not_reached": "target NOT reached (a target is a goal, not a promise)",
        "blocked": "Large images not resized because their scale needs a manual fix: {n}",
        "dry_head": "Dry run only. No file was changed.", "size_only": "This is disk size only, not RAM or FPS.",
        "resized_warn": "Resized images: the atlas XML and the character JSON scale were edited. Test them in game; this has not been tested.",
        "created": "New copy created:\n{dest}\nThe original mod was not changed.", "disk": "Sizes were verified from the files actually on disk.",
        "why": "Reason: {r}",
        "dry": "Dry run only. No file was changed.\nPNGs examined: {n}\nCan be shrunk safely: {ok}\nSkipped: {skip}\nFailed checks: {fail}\nExpected saving: {saved} (of {orig})\nThis is disk size only, not RAM or FPS.\n\nBiggest savings:",
        "apply_ok": "New copy created:\n{dest}\nThe original mod was not changed.\nPNGs examined: {n}\nChanged: {chg}\nSkipped: {skip}\nFailed: {fail}\nBefore: {orig}\nAfter: {final}\nSaved: {saved}\nNot tested in game yet.",
        "failed": "Operation failed. No folder was created and the original is untouched.\nReason: {why}",
        "cancelled": "Cancelled. No folder was created and the original is untouched.",
        "path": "Path problem: {why}",
        "error": "Unexpected error: {why}",
        "manifest": "Operation log: {p}",
        "partial": "Note: the scan was cancelled; results are incomplete.",
        "unknown": "Unknown command: {c}",
    },
}


def fmt(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024


def cancel():
    _cancel.set()


def progress():
    return json.dumps(get_progress())


def run(cmd, mod, output, workspace, lang="en", options="{}"):
    t = T.get(lang, T["en"])
    opts = json.loads(options or "{}")
    _cancel.clear()
    try:
        if cmd in ("scan", "atlas"):
            validate_roots(mod)  # a wrong path must be an error, not "0 files"
        if cmd == "scan":
            s = summarize(scan(mod, _cancel))
            lines = [t["scan"].format(files=s["file_count"], size=fmt(s["total_bytes"]),
                                      bad=len(s["parse_failures"]), unk=s["unknown_type_files"])]
            lines += [f"{fmt(f['size'])}  {f['rel_path']}" for f in s["largest_files"][:10]]
            if s["parse_failures"]:
                lines += ["", "JSON/XML:"] + s["parse_failures"][:10]
            if _cancel.is_set():
                lines.insert(0, t["partial"])
            return _out(True, "\n".join(lines))
        if cmd == "atlas":
            res = check_atlases(mod)
            counts = {}
            for r in res:
                counts[r["status"]] = counts.get(r["status"], 0) + 1
            lines = [t["atlas"].format(n=len(res), counts="\n".join(f"{k}: {v}" for k, v in sorted(counts.items())))]
            bad = [r for r in res if r["status"] not in ("OK", "NOT_ATLAS")]
            lines += [f"{r['status']} | {r['xml']} {' '.join(r['notes'])[:80]}" for r in bad[:15]] or [t["atlas_ok"]]
            return _out(True, "\n".join(lines))
        if cmd in ("dry", "apply"):
            apply = cmd == "apply"
            st = Settings(mode=opts.get("mode", "lossless"), allow_resize=bool(opts.get("allow_resize", False)),
                          scale=float(opts.get("scale", 0.5)), target_pct=float(opts.get("target_pct", 45)))
            m = optimize_mod(mod, workspace, output if apply else None, apply, cancel=_cancel, settings=st)
            return _out(m["status"] in ("SUCCESS", "WARNING"), _optimize_text(m, t, apply, output, bool(opts.get("detailed", True))))
        return _out(False, t["unknown"].format(c=cmd))
    except PathError as e:
        return _out(False, t["path"].format(why=e))
    except Exception as e:  # shown to the user, never swallowed
        return _out(False, t["error"].format(why=f"{type(e).__name__}: {e}"))


def _optimize_text(m, t, apply, output, detailed):
    if m["status"] == "CANCELLED":
        return t["cancelled"]
    if m["status"] == "FAILED":
        return t["failed"].format(why="; ".join(m["errors"]) or "?")
    s, imgs = m["summary"], m["images"]
    pct = lambda v: f"{v:.1f}%"
    head = t["created"].format(dest=output) if apply else t["dry_head"]
    body = t["opt"].format(mode=m["settings"]["mode"] + (" + resize" if m["settings"]["resize_active"] else ""),
                           orig=fmt(s["png_original_bytes"]), final=fmt(s["png_final_bytes"]), pct=pct(s["total_reduction_pct"]),
                           ll=fmt(s["lossless_saved_bytes"]), llpct=pct(s["lossless_reduction_pct"]), rs=fmt(s["resize_saved_bytes"]),
                           target=f"{s['target_pct']:g}", reached=t["reached"] if s["target_reached"] else t["not_reached"],
                           nl=s["optimized_lossless"], nr=s["optimized_resized"], un=s["unchanged"], sk=s["skipped"], fail=s["failed"])
    lines = [head, body]
    if s["resize_blocked_needs_manual_fix"]:
        lines.append(t["blocked"].format(n=s["resize_blocked_needs_manual_fix"]))
    if s["optimized_resized"]:
        lines.append(t["resized_warn"])
    lines.append(t["disk"] if apply else t["size_only"])
    if detailed:
        rows = sorted((i for i in imgs if i["stage"] != "none"), key=lambda i: i["bytes_saved"], reverse=True)[:10]
        lines += [""] + [f"-{fmt(i['bytes_saved'])}  [{i['stage']}] {i['rel_path']}" for i in rows]
        failed = [i for i in imgs if i["status"] == "FAILED"][:5]
        if failed:
            lines += ["", "FAILED:"] + [f"{i['rel_path']}: {i['reason']}" for i in failed]
        skipped = [r for r in m["resize"] if r["status"] == "SKIPPED" and r["reason"]][:5]
        if skipped:
            lines += ["", "RESIZE SKIPPED:"] + [f"{r['rel_path']}: {r['reason'][:110]}" for r in skipped]
    lines += ["", t["manifest"].format(p=str(Path(m["workspace"]) / f"manifest-{m['operation_id']}.json"))]
    return "\n".join(lines)


def workspace_of(m):
    return m.get("workspace", "")


def _out(ok, text):
    return json.dumps({"ok": ok, "text": text}, ensure_ascii=False)
