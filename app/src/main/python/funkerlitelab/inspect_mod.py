"""Mod structure and engine-hint detection. Conclusions carry a confidence and their evidence."""
import json
import os
from collections import Counter
from pathlib import Path

from .adapters import detect_atlas, describe_adapters
from .scanner import scan, summarize

PSYCH_FOLDERS = ["characters", "stages", "weeks", "songs", "data", "images", "scripts", "custom_events",
                 "custom_notetypes", "sounds", "music", "videos", "shaders", "fonts"]
CHAR_KEYS = {"animations", "image", "scale", "sing_duration", "healthicon", "position", "camera_position",
             "healthbar_colors", "flip_x", "no_antialiasing"}
STAGE_KEYS = {"directory", "defaultZoom", "boyfriend", "girlfriend", "opponent", "hide_girlfriend", "camera_boyfriend",
              "camera_opponent", "camera_girlfriend", "camera_speed", "isPixelStage"}
WEEK_KEYS = {"songs", "weekCharacters", "weekBackground", "storyName", "weekName", "startUnlocked", "hideStoryMode"}


def _load(p):
    try:
        return json.loads(p.read_bytes().decode("utf-8-sig"))
    except (ValueError, OSError):
        return None


def inspect_mod(root):
    root = Path(root)
    records = list(scan(root))
    s = summarize(records)
    folders = sorted(d.name for d in root.iterdir() if d.is_dir())
    present = [f for f in PSYCH_FOLDERS if f in folders]
    evidence, unknown_keys = [], Counter()
    schema = {"character": 0, "stage": 0, "week": 0}
    for sub, keys, label in (("characters", CHAR_KEYS, "character"), ("stages", STAGE_KEYS, "stage"), ("weeks", WEEK_KEYS, "week")):
        d = root / sub
        if d.is_dir():
            for p in d.rglob("*.json"):
                j = _load(p)
                if isinstance(j, dict):
                    hit = set(j) & keys
                    if len(hit) >= 3:
                        schema[label] += 1
                        unknown_keys.update(k for k in j if k not in keys)
    if schema["character"]:
        evidence.append(f"{schema['character']} character JSON(s) match the Psych-style schema")
    if schema["stage"]:
        evidence.append(f"{schema['stage']} stage JSON(s) match the Psych-style schema")
    if schema["week"]:
        evidence.append(f"{schema['week']} week JSON(s) match the Psych-style schema")
    pack = _load(root / "pack.json") if (root / "pack.json").is_file() else None
    if isinstance(pack, dict):
        evidence.append("pack.json present (mod folder metadata used by Psych Engine mod loader)")
    if len(present) >= 3:
        evidence.append(f"standard folders: {', '.join(present)}")
    conf = "high" if len(evidence) >= 3 else "medium" if len(evidence) == 2 else "low" if evidence else "none"
    scripts = Counter(Path(r.rel_path).suffix.lower() for r in records if r.ext in (".lua", ".hx", ".hscript"))
    formats = Counter()
    for r in records:
        if r.ext == ".png":
            a, _ = detect_atlas(root, r.rel_path)
            formats[a.name if a else "plain-or-unknown"] += 1
    unknown_exts = Counter(r.ext or "(none)" for r in records if r.category == "unknown")
    return {
        "engine_guess": {"engine": "Psych Engine (or a fork)" if conf in ("high", "medium") else "unknown",
                         "confidence": conf, "evidence": evidence,
                         "version": "unknown - mod files alone cannot establish the engine version; "
                                    "provide the engine version/build for a firm answer",
                         "schema_keys_not_in_known_list": dict(unknown_keys.most_common(15))},
        "folders_present": present, "other_folders": [f for f in folders if f not in PSYCH_FOLDERS],
        "has_lua": scripts.get(".lua", 0) > 0, "has_hscript": (scripts.get(".hx", 0) + scripts.get(".hscript", 0)) > 0,
        "script_counts": dict(scripts), "png_atlas_formats": dict(formats),
        "unrecognized_file_types": dict(unknown_exts.most_common(15)),
        "inventory": {k: s[k] for k in ("file_count", "total_bytes", "bytes_by_category", "parse_failures", "unknown_type_files")},
        "adapters": describe_adapters(),
    }
