import argparse
import json
import sys
from pathlib import Path

from .atlas import check_atlases
from .operation import MODES, Settings, optimize_mod
from .paths import PathError
from .scanner import scan, summarize
from .zipcheck import PSYCH_DIRS, inspect_zip

DEFAULTS = {"max_pixels": 70_000_000, "workspace": "~/FunkerLiteLab/workspace", "resize_enabled": False}


def load_config(path):
    cfg = dict(DEFAULTS)
    p = Path(path).expanduser()
    if p.is_file():
        cfg.update(json.loads(p.read_text(encoding="utf-8")))
    return cfg


def write_report(report, mod, data):
    rp, mp = Path(report).expanduser().resolve(), Path(mod).expanduser().resolve()
    if rp == mp or mp in rp.parents:
        sys.exit("Refusing to write a report inside the mod folder.")
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Report written:", rp, file=sys.stderr)


def list_mods(mods_dir):
    out = []
    for d in sorted(Path(mods_dir).iterdir(), key=lambda p: p.name.lower()):
        if d.is_dir():
            top = {c.name for c in d.iterdir() if c.is_dir()}
            s = summarize(scan(d))
            out.append({"mod": d.name, "psych_folders": sorted(top & PSYCH_DIRS), "files": s["file_count"],
                        "total_bytes": s["total_bytes"], "bytes_by_category": s["bytes_by_category"],
                        "parse_failures": s["parse_failures"],
                        "verdict": "looks like a Psych mod (heuristic)" if len(top & PSYCH_DIRS) >= 3 else "not recognized"})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="funkerlitelab", description="Read-only analysis and safe lossless PNG optimization.")
    ap.add_argument("--config", default="~/FunkerLiteLab/config.json")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, helptext in (("scan", "inventory one mod"), ("atlas", "check XML atlases of one mod")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("mod"); s.add_argument("--report")
    m = sub.add_parser("mods", help="list every mod in a mods folder"); m.add_argument("mods_dir"); m.add_argument("--report")
    z = sub.add_parser("zipcheck", help="inspect a mod ZIP without extracting"); z.add_argument("zipfile")
    o = sub.add_parser("optimize", help="lossless PNG optimization (dry-run unless --apply)")
    o.add_argument("mod"); o.add_argument("--output"); o.add_argument("--apply", action="store_true")
    o.add_argument("--workspace")
    o.add_argument("--mode", choices=MODES, default="lossless")
    o.add_argument("--allow-resize", action="store_true", help="REQUIRED for any resizing (balanced/aggressive only)")
    o.add_argument("--scale", type=float, default=0.5, help="requested scale, e.g. 0.5 = half size")
    o.add_argument("--target", type=float, default=45.0, help="target reduction in percent (a goal, not a promise)")
    o.add_argument("--keep-metadata", action="store_true")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    try:
        if a.cmd == "scan":
            data = summarize(scan(a.mod))
        elif a.cmd == "atlas":
            res = check_atlases(a.mod)
            data = {"atlases": res, "status_counts": {k: sum(r["status"] == k for r in res) for k in sorted({r["status"] for r in res})}}
        elif a.cmd == "mods":
            data = list_mods(a.mods_dir)
        elif a.cmd == "zipcheck":
            data = inspect_zip(a.zipfile)
        else:
            if a.apply and not a.output:
                sys.exit("--apply needs --output (a NEW folder; existing folders are never touched)")
            st = Settings(mode=a.mode, allow_resize=a.allow_resize, scale=a.scale, target_pct=a.target,
                          max_pixels=cfg["max_pixels"], strip_metadata=not a.keep_metadata)
            m = optimize_mod(a.mod, Path(a.workspace or cfg["workspace"]).expanduser(), a.output, a.apply, settings=st)
            data = {k: m.get(k) for k in ("mode", "status", "summary", "errors", "operation_id", "settings")}
        print(json.dumps(data, indent=2, ensure_ascii=False))
        if getattr(a, "report", None):
            write_report(a.report, a.mod if hasattr(a, "mod") else a.mods_dir, data)
    except PathError as e:
        sys.exit(str(e))
    except (FileNotFoundError, NotADirectoryError) as e:
        sys.exit(f"Path problem: {e}")


if __name__ == "__main__":
    main()
