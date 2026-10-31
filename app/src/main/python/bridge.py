"""Thin layer between the Android UI (Kotlin) and the engine. Returns JSON text.
All real work lives in funkerlitelab/; nothing here decides safety."""
import json
import threading
from pathlib import Path

from funkerlitelab.atlas import check_atlases
from funkerlitelab.depgraph import build_graph
from funkerlitelab.diagnostics import build_report, render_text
from funkerlitelab.inspect_mod import inspect_mod
from funkerlitelab.validate import validate_output
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
        "ladder": "مراحل التحقق:\n1 التحليل: {a}\n2 التحسين: {o}\n3 التحقق من الهيكل: {st}\n4 الفحص الثابت للتوافق: {sc}\n5 تجربة المحرك الحقيقي: لم تتم\n6 تجربة اللعب على الموبايل: لم تتم (دورك أنت)",
        "done": "تم", "dry_only": "تجربة فقط، لم يتم إنشاء نسخة", "not_run": "لم يتم",
        "inspect": "المحرك المرجح: {engine} (ثقة: {conf})\nالدليل: {ev}\nالإصدار: غير معروف من ملفات المود لوحدها\nالمجلدات: {folders}\nسكربتات Lua: {lua} | HScript: {hx}\nأنواع الأطلس: {atl}\nملفات غير معروفة: {unk}\n\nالعلاقات بين الملفات: {edges}\nمراجع ديناميكية في السكربتات (ما نقدرش نحلّلها): {dyn}\nصور مالهاش مرجع ثابت (ده مش معناه إنها مش مستخدمة): {orph}",
        "validate_head": "التحقق الثابت (ده مش تجربة في اللعبة)\nمقارنة: المود الأصلي ← النسخة المحسنة\nجاهز للتجربة اليدوية: {ready}",
        "no_manifest": "مفيش عملية سابقة في مجلد العمل.",
        "report_saved": "تقرير التشخيص اتحفظ في: {p}\nمفيهوش محتوى ملفات ولا مسارات كاملة. ابعته لي زي ما هو.",
        "need_both": "اكتب مسار المود الأصلي ومسار النسخة المحسنة الأول.",
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
        "ladder": "Status ladder:\n1 Analysis: {a}\n2 Optimization: {o}\n3 Structural validation: {st}\n4 Static compatibility checks: {sc}\n5 Real engine test: not done\n6 Manual Android gameplay test: not done (your step)",
        "done": "done", "dry_only": "dry run only, no copy created", "not_run": "not run",
        "inspect": "Likely engine: {engine} (confidence: {conf})\nEvidence: {ev}\nVersion: not determinable from mod files alone\nFolders: {folders}\nLua scripts: {lua} | HScript: {hx}\nAtlas types: {atl}\nUnrecognized files: {unk}\n\nFile relationships: {edges}\nRuntime-built references in scripts (cannot be analyzed): {dyn}\nImages with no static reference (NOT proof of unused): {orph}",
        "validate_head": "Static validation (this is NOT an in-game test)\nComparing: original mod -> optimized copy\nReady for manual testing: {ready}",
        "no_manifest": "No previous run found in the workspace.",
        "report_saved": "Diagnostic report saved to: {p}\nIt contains no file contents or full paths. Send it as is.",
        "need_both": "Enter the original mod path and the optimized copy path first.",
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
        if cmd == "inspect":
            validate_roots(mod)
            i, g = inspect_mod(mod), build_graph(mod)
            eg = i["engine_guess"]
            return _out(True, t["inspect"].format(
                engine=eg["engine"], conf=eg["confidence"], ev="; ".join(eg["evidence"]) or "-",
                folders=", ".join(i["folders_present"]) or "-", lua=i["script_counts"].get(".lua", 0),
                hx=i["script_counts"].get(".hx", 0) + i["script_counts"].get(".hscript", 0),
                atl=", ".join(f"{k}={v}" for k, v in i["png_atlas_formats"].items()) or "-",
                unk=", ".join(f"{k}={v}" for k, v in i["unrecognized_file_types"].items()) or "-",
                edges=", ".join(f"{k}={v}" for k, v in g["edge_counts"].items()) or "-",
                dyn=len(g["dynamic_references"]), orph=len(g["images_without_static_reference"])))
        if cmd == "validate":
            if not output:
                return _out(False, t["need_both"])
            validate_roots(mod)
            v = validate_output(mod, output)
            lines = [t["validate_head"].format(ready=v["ready_for_manual_test"]), ""]
            for c in v["checks"]:
                lines.append(f"[{c['state']}] {c['name']}: {c['detail']}")
                lines += [f"    - {f}" for f in c["files"][:5]]
            return _out(v["static"] != "FAILED", "\n".join(lines))
        if cmd == "report":
            files = sorted(Path(workspace).glob("manifest-*.json"), key=lambda p: p.stat().st_mtime)
            if not files:
                return _out(False, t["no_manifest"])
            rep_text = render_text(build_report(json.loads(files[-1].read_text())))
            out_path = Path(workspace) / ("diagnostic-" + files[-1].stem.split("-", 1)[1] + ".txt")
            out_path.write_text(rep_text, encoding="utf-8")
            return json.dumps({"ok": True, "text": t["report_saved"].format(p=out_path) + "\n\n" + rep_text,
                               "share": rep_text}, ensure_ascii=False)
        if cmd in ("dry", "apply"):
            apply = cmd == "apply"
            st = Settings(mode=opts.get("mode", "lossless"), allow_resize=bool(opts.get("allow_resize", False)),
                          scale=opts.get("scale", "auto"), target_pct=float(opts.get("target_pct", 45)),
                          exclude=list(opts.get("exclude", [])))
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
        f = m.get("failure") or {}
        where = f"{f.get('stage')} / {f.get('file')}" if f.get("file") else str(f.get("stage"))
        return t["failed"].format(why=("[" + where + "] " if f else "") + ("; ".join(m["errors"]) or "?"))
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
        lines += [""] + [f"-{fmt(i['bytes_saved'])}  [{i['stage']}{' x%.2f' % i['resize_factor'] if i.get('resize_factor') else ''}] {i['rel_path']}" for i in rows]
        failed = [i for i in imgs if i["status"] == "FAILED"][:5]
        if failed:
            lines += ["", "FAILED:"] + [f"{i['rel_path']}: {i['reason']}" for i in failed]
        skipped = [r for r in m["resize"] if r["status"] == "SKIPPED" and r["reason"]][:5]
        if skipped:
            lines += ["", "RESIZE SKIPPED:"] + [f"{r['rel_path']}: {r['reason'][:110]}" for r in skipped]
    if apply and m.get("validation"):
        v = m["validation"]
        lines += ["", t["ladder"].format(a=t["done"], o=t["done"], st=v["structural"], sc=v["static"])]
    elif not apply:
        lines += ["", t["ladder"].format(a=t["done"], o=t["dry_only"], st=t["not_run"], sc=t["not_run"])]
    lines += ["", t["manifest"].format(p=str(Path(m["workspace"]) / f"manifest-{m['operation_id']}.json"))]
    return "\n".join(lines)


def workspace_of(m):
    return m.get("workspace", "")


def _out(ok, text):
    return json.dumps({"ok": ok, "text": text}, ensure_ascii=False)
