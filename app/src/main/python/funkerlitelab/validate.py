"""Output validation. Compares an optimized copy with its source and reports explicit states.

This is STATIC validation. It never launches the game; 'engine test' and 'manual gameplay test' are always
reported as NOT_TESTED here. A pass means: no inconsistency was found by the checks listed, nothing more.
"""
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

from .atlas import check_atlases
from .atlas_scale import _parse_xml, _r
from .depgraph import build_graph
from .hashing import sha256_file

PASSED, FAILED, WARNING, INCONCLUSIVE, NOT_TESTED = "PASSED", "FAILED", "WARNING", "INCONCLUSIVE", "NOT_TESTED"


def _files(root):
    out = {}
    for dp, dn, fn in os.walk(root, followlinks=False):
        for n in fn:
            p = Path(dp) / n
            if not p.is_symlink():
                out[p.relative_to(root).as_posix()] = p
    return out


def _check(name, state, detail, files=None):
    return {"name": name, "state": state, "detail": detail, "files": (files or [])[:20], "file_count": len(files or [])}


def validate_output(src, out, expected_changes=None, src_hashes=None):
    """expected_changes: set of relative paths the operation meant to modify (None = unknown, e.g. validating an
    old output after the fact). Returns {"checks": [...], "structural": state, "static": state, ...}."""
    src, out = Path(src), Path(out)
    sf, of = _files(src), _files(out)
    checks = []
    missing, extra = sorted(set(sf) - set(of)), sorted(set(of) - set(sf))
    checks.append(_check("structure: relative paths and filenames preserved",
                         FAILED if missing else WARNING if extra else PASSED,
                         f"{len(missing)} missing, {len(extra)} extra file(s)", missing + extra))
    differing = []
    for rel in sorted(set(sf) & set(of)):
        if sf[rel].stat().st_size != of[rel].stat().st_size:
            differing.append(rel)
            continue
        h = src_hashes.get(rel) if src_hashes else None
        if (h or sha256_file(sf[rel])) != sha256_file(of[rel]):
            differing.append(rel)
    if expected_changes is not None:
        unexpected = [r for r in differing if r not in expected_changes]
        notchanged = [r for r in expected_changes if r in sf and r not in differing]
        checks.append(_check("untouched files are byte-identical to the source",
                             FAILED if unexpected else PASSED,
                             f"{len(unexpected)} file(s) changed that the operation did not plan to change", unexpected))
        if notchanged:
            checks.append(_check("planned changes present", WARNING, f"{len(notchanged)} planned change(s) not found", notchanged))
    else:
        checks.append(_check("files that differ from the source", INCONCLUSIVE if differing else PASSED,
                             f"{len(differing)} file(s) differ (the plan is unknown, so they cannot be judged unexpected)", differing))
    bad, resized = [], {}
    for rel in differing:
        if rel.lower().endswith(".png"):
            try:
                with Image.open(of[rel]) as im:
                    im.load()
                    size = im.size
                with Image.open(sf[rel]) as im0:
                    size0 = im0.size
                if size != size0:
                    resized[rel] = (size0, size)
            except Exception as e:
                bad.append(f"{rel}: {type(e).__name__}: {e}")
    checks.append(_check("changed PNG files decode", FAILED if bad else PASSED, f"{len(bad)} failed to decode", bad))
    bad = []
    for rel in differing:
        if rel.lower().endswith((".xml", ".json")):
            try:
                raw = of[rel].read_bytes()
                if rel.lower().endswith(".json"):
                    json.loads(raw.decode("utf-8-sig"))
                else:
                    ET.fromstring(raw)
            except Exception as e:
                bad.append(f"{rel}: {type(e).__name__}: {e}")
    checks.append(_check("changed XML/JSON files parse", FAILED if bad else PASSED, f"{len(bad)} do not parse", bad))
    # atlases: anything that was fine in the source must still be fine
    sa = {a["xml"]: a["status"] for a in check_atlases(src)}
    broke, pre = [], []
    for a in check_atlases(out):
        if a["status"] in ("OK", "NOT_ATLAS"):
            continue
        (broke if sa.get(a["xml"]) in ("OK", "NOT_ATLAS", None) else pre).append(f"{a['xml']}: {a['status']}")
    checks.append(_check("atlas frames fit their images (every XML)", FAILED if broke else WARNING if pre else PASSED,
                         f"{len(broke)} atlas(es) newly broken, {len(pre)} already problematic in the source", broke + pre))
    # resized atlases: frames scaled consistently AND character scale compensated
    prob = []
    for rel, (s0, s1) in resized.items():
        fx, fy = s1[0] / s0[0], s1[1] / s0[1]
        xr = Path(rel).with_suffix(".xml").as_posix()
        if xr not in sf or xr not in of:
            prob.append(f"{rel}: resized {s0}->{s1} but there is no atlas XML on both sides")
            continue
        try:
            a = [n for n in _parse_xml(sf[xr].read_bytes().decode("utf-8-sig")).iter("SubTexture")]
            b = [n for n in _parse_xml(of[xr].read_bytes().decode("utf-8-sig")).iter("SubTexture")]
        except Exception as e:
            prob.append(f"{xr}: {type(e).__name__}: {e}")
            continue
        if [n.get("name") for n in a] != [n.get("name") for n in b]:
            prob.append(f"{xr}: frame names/count differ from the source")
            continue
        worst = 0
        for n0, n1 in zip(a, b):
            for k, f in (("x", fx), ("y", fy), ("width", fx), ("height", fy), ("frameX", fx), ("frameY", fy),
                         ("frameWidth", fx), ("frameHeight", fy)):
                if n0.get(k) is not None:
                    want = float(n0.get(k)) * f
                    got = float(n1.get(k)) if n1.get(k) is not None else 1e9
                    worst = max(worst, abs(got - want))
        if worst > 1.5:
            prob.append(f"{xr}: a frame value is {worst:.1f}px away from the expected scaled value")
        # character JSONs that name this image
        key = os.path.splitext(rel.split("images/", 1)[-1])[0].lower()
        for jrel in (r for r in sf if r.lower().startswith("characters/") and r.lower().endswith(".json")):
            try:
                j0 = json.loads(sf[jrel].read_bytes().decode("utf-8-sig"))
                j1 = json.loads(of[jrel].read_bytes().decode("utf-8-sig"))
            except Exception:
                continue
            if isinstance(j0, dict) and str(j0.get("image", "")).replace("\\", "/").lower() == key:
                s_old, s_new = j0.get("scale", 1), j1.get("scale", 1)
                if not (isinstance(s_old, (int, float)) and isinstance(s_new, (int, float))) or abs(s_new * fx / s_old - 1) > 0.01:
                    prob.append(f"{jrel}: scale {s_old} -> {s_new} does not compensate the {fx:.2f}x image resize")
    checks.append(_check("resized atlases: frames scaled and character scale compensated",
                         FAILED if prob else (PASSED if resized else PASSED),
                         (f"{len(resized)} resized image(s), {len(prob)} problem(s)" if resized else "no resized images"), prob))
    # references must not get worse
    g0, g1 = build_graph(src), build_graph(out)
    miss0 = {(e["from"], e["to"]) for e in g0["edges"] if e["confidence"] == "unresolved"}
    new_miss = [f"{e['from']} -> {e['to']}" for e in g1["edges"] if e["confidence"] == "unresolved" and (e["from"], e["to"]) not in miss0]
    checks.append(_check("known references still resolve", FAILED if new_miss else (WARNING if miss0 else PASSED),
                         f"{len(new_miss)} newly unresolved reference(s); {len(miss0)} already unresolved in the source", new_miss))
    if g1["dynamic_references"]:
        checks.append(_check("runtime-built references", INCONCLUSIVE,
                             "script calls build image names at run time; static checks cannot cover them",
                             [f"{d['file']}:{d['line']}" for d in g1["dynamic_references"]]))
    checks.append(_check("real engine load test", NOT_TESTED, "no engine build was run"))
    checks.append(_check("manual Android gameplay test", NOT_TESTED, "must be done by you on the phone"))
    structural_names = ("structure", "changed PNG", "untouched", "changed XML")
    struct_failed = any(c["state"] == FAILED for c in checks if c["name"].startswith(structural_names))
    static_failed = any(c["state"] == FAILED for c in checks)
    return {"checks": checks, "structural": FAILED if struct_failed else PASSED,
            "static": FAILED if static_failed else (WARNING if any(c["state"] in (WARNING, INCONCLUSIVE) for c in checks) else PASSED),
            "engine_test": NOT_TESTED, "manual_test": NOT_TESTED, "changed_files": len(differing),
            "ready_for_manual_test": not static_failed,
            "note": "Static validation only. It does not prove the mod works in game."}
