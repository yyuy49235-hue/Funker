"""Reference graph. Every edge says how it was found and how sure we are:
  confirmed  - atlas imagePath resolves; character JSON image resolves; a literal passed to a known loader call
  unresolved - target not found in this mod; it may be a base-game asset the engine supplies, or truly missing
  inferred   - an image path appears as a string literal somewhere else (could be used, could be a comment)
  dynamic    - a loader call whose argument is built at run time (cannot be resolved statically)
Images with no incoming edge are listed as 'no static reference found' - NOT as unused."""
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .atlas import resolve_image
from .atlas import resolve_image
from .references import TEXT_EXTS, MAX_TEXT, image_key

LOADERS_TAG_FIRST = ("makeluasprite", "makeanimatedluasprite", "loadgraphic", "loadframes")
_CALL = re.compile(r"""\b(makeLuaSprite|makeAnimatedLuaSprite|loadGraphic|loadFrames|precacheImage|makeLuaBackdrop)\s*\(([^)\n]*)\)""", re.I)
_LIT = re.compile(r"""(["'])(.*?)\1""")
_STR = re.compile(r"""["']([^"'\n]{1,200})["']""")


def build_graph(root):
    root = Path(root)
    imgs = {}            # key -> rel png
    texts = []           # (rel, text)
    for dp, dn, fn in os.walk(root, followlinks=False):
        for n in fn:
            p = Path(dp) / n
            if p.is_symlink():
                continue
            rel = p.relative_to(root).as_posix()
            if p.suffix.lower() == ".png":
                k = image_key(rel)
                if k:
                    imgs[k] = rel
            elif p.suffix.lower() in TEXT_EXTS:
                try:
                    if p.stat().st_size <= MAX_TEXT:
                        texts.append((rel, p.read_bytes().decode("utf-8-sig", errors="replace")))
                except OSError:
                    pass
    edges, dynamic = [], []

    def add(src, dst, kind, conf, ev):
        edges.append({"from": src, "to": dst, "kind": kind, "confidence": conf, "evidence": ev})

    for rel, text in texts:
        low = rel.lower()
        if low.endswith(".xml"):
            try:
                r = ET.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", text, count=1).encode("utf-8"))
            except ET.ParseError:
                continue
            name = r.get("imagePath")
            if name and any(n.tag == "SubTexture" for n in r.iter()):
                hit, how = resolve_image(root / Path(rel).parent, name)
                target = (Path(rel).parent / name).as_posix()
                if hit is not None:
                    add(rel, hit.relative_to(root).as_posix(), "describes", "confirmed", f"imagePath resolves ({how})")
                else:
                    alt, how = resolve_image(root / Path(rel).parent, name)
                    if alt is not None:
                        add(rel, alt.relative_to(root).as_posix(), "describes", "inferred",
                            f"imagePath '{name}' differs from the real file name ({how}); the engine may load by file name instead")
                    else:
                        add(rel, target, "describes", "unresolved", "imagePath does not resolve next to the XML (suspected missing)")
            continue
        if low.endswith(".json") and low.startswith("characters/"):
            try:
                d = json.loads(text)
            except ValueError:
                continue
            if isinstance(d, dict) and isinstance(d.get("image"), str):
                img = d["image"].replace("\\", "/").lower()
                cands = [img]
                if "idle_anim" in d or "confirm_anim" in d:      # menu-character schema: image lives in images/menucharacters/
                    cands.insert(0, "menucharacters/" + img)
                k = next((c for c in cands if c in imgs), None)
                if k:
                    add(rel, imgs[k], "uses", "confirmed", f'"image": "{d["image"]}"')
                else:
                    add(rel, "images/" + cands[0] + ".png", "uses", "unresolved",
                        f'"image": "{d["image"]}" not found in this mod (may come from the engine base assets)')
                continue
        is_script = low.endswith((".lua", ".hx", ".hscript"))
        called = set()
        if is_script:
            for m in _CALL.finditer(text):
                fn, args = m.group(1).lower(), m.group(2)
                lits = [x[1] for x in _LIT.findall(args)]
                line = text.count("\n", 0, m.start()) + 1
                if ".." in args or (not lits and fn != "precacheimage"):
                    dynamic.append({"file": rel, "line": line, "call": m.group(1)})
                    continue
                want = (lits[1] if fn in LOADERS_TAG_FIRST and len(lits) > 1 else lits[0] if lits else None)
                if want:
                    k = want.replace("\\", "/").lower()
                    called.add(k)
                    if k in imgs:
                        add(rel, imgs[k], "loads", "confirmed", f"{m.group(1)}(...'{want}'...) line {line}")
                    else:
                        add(rel, "images/" + want + ".png", "loads", "unresolved", f"{m.group(1)} line {line}: not in this mod (may come from the engine base assets)")
        seen = set()
        for lit in _STR.findall(text):
            k = lit.replace("\\", "/").lower()
            if k in imgs and k not in called and k not in seen:
                seen.add(k)
                add(rel, imgs[k], "mentions", "inferred", f"string literal '{lit}'")
    referenced = {e["to"] for e in edges if e["confidence"] != "unresolved"}
    orphans = sorted(v for v in imgs.values() if v not in referenced)
    conf = {}
    for e in edges:
        conf[e["confidence"]] = conf.get(e["confidence"], 0) + 1
    return {"images": len(imgs), "edges": edges, "edge_counts": conf, "dynamic_references": dynamic,
            "images_without_static_reference": orphans,
            "limits": "Static scan only. Runtime-built names (string concatenation, variables) cannot be resolved; "
                      "'no static reference' does not mean unused. Lua was read as text and never executed."}
