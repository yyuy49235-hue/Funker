"""Static reference index used to decide which atlases can be downscaled with a provable fix.

An image is "compensable" only if ALL of this holds:
  * it has a Sparrow XML next to it (same name) whose imagePath points back to it,
  * at least one character JSON (under characters/) names it in its "image" field,
  * no other text file (Lua, other JSON, hx, txt, ini...) mentions its path.
Anything else is reported as blocked, with the reason. Dynamic Lua code that builds names at run time
cannot be seen by a static scan; that limit is stated in every report.
"""
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .adapters import detect_atlas

TEXT_EXTS = {".lua", ".json", ".hx", ".txt", ".ini", ".cfg", ".yaml", ".yml", ".xml", ".frag", ".vert"}
MAX_TEXT = 5 * 1024 * 1024


# scripts that resize/scale the stage characters: automatic compensation cannot be proven when these exist
SCRIPT_SCALE = re.compile(
    r"""(boyfriend|dad|gf|bf|opponent)\w*\.scale|scaleobject\(\s*['"](boyfriend|dad|gf)|setgraphicsize\(\s*['"](boyfriend|dad|gf)"""
    r"""|setproperty\(\s*['"](boyfriend|dad|gf)\w*\.scale""", re.I)


def image_key(rel_png):
    """'images/characters/Tabi.png' -> 'characters/tabi' (None if not under images/)."""
    parts = Path(rel_png).as_posix().split("/")
    if "images" not in parts:
        return None
    rest = "/".join(parts[parts.index("images") + 1:])
    return os.path.splitext(rest)[0].lower()


def _read_text(path):
    try:
        if path.stat().st_size > MAX_TEXT:
            return None
        return path.read_bytes().decode("utf-8-sig", errors="replace")
    except OSError:
        return None


def index_references(root):
    root = Path(root)
    char_json, others = {}, []
    for dp, dn, fn in os.walk(root, followlinks=False):
        for n in fn:
            p = Path(dp) / n
            if p.is_symlink() or p.suffix.lower() not in TEXT_EXTS:
                continue
            rel = p.relative_to(root).as_posix()
            text = _read_text(p)
            if text is None:
                continue
            if p.suffix.lower() == ".json" and rel.lower().startswith("characters/"):
                try:
                    d = json.loads(text)
                except ValueError:
                    d = None
                if isinstance(d, dict) and isinstance(d.get("animations"), list) and isinstance(d.get("image"), str):
                    char_json.setdefault(d["image"].replace("\\", "/").lower(), []).append(rel)
                    continue
            others.append((rel, text.lower()))
    scale_scripts = [rel for rel, text in others if rel.endswith((".lua", ".hx", ".hscript")) and SCRIPT_SCALE.search(text)]
    return {"char_json": char_json, "texts": others, "scale_scripts": scale_scripts}


def _mentions(text_lower, key):
    return re.search(r"(?<![a-z0-9_])" + re.escape(key) + r"(?![a-z0-9_])", text_lower) is not None


def check_compensable(root, rel_png, refs):
    """Return (ok, reasons, info). info = {xml, char_jsons}."""
    root = Path(root)
    reasons, warnings = [], []
    key = image_key(rel_png)
    if key is None:
        return False, ["not inside an images/ folder"], {}
    xml_rel = Path(rel_png).with_suffix(".xml").as_posix()
    xml_path = root / xml_rel
    adapter, ainfo = detect_atlas(root, rel_png)
    if adapter is not None and not adapter.can_scale:
        reasons.append(f"atlas format '{adapter.name}' is recognized but resizing it is not supported")
    elif ainfo.get("refuse"):
        reasons.append(f"Sparrow atlas not supported: {ainfo.get('detail')}")
    if not xml_path.is_file():
        if adapter is None:
            reasons.append("no atlas metadata next to the image (plain images are not resized: their scale lives in scripts)")
    else:
        try:
            r = ET.parse(xml_path).getroot()
            if not any(n.tag == "SubTexture" for n in r.iter()):
                reasons.append("XML has no SubTexture frames")
            elif os.path.basename(r.get("imagePath", "")).lower() != Path(rel_png).name.lower():
                warnings.append(f"XML imagePath '{r.get('imagePath')}' differs from the file name; resizing keeps both unchanged "
                                "(assumes the engine loads the atlas by file name - not verified against engine source)")
        except ET.ParseError:
            reasons.append("XML does not parse")
    if refs.get("scale_scripts"):
        reasons.append("script(s) alter character scale (" + ", ".join(refs["scale_scripts"][:2]) +
                       "); automatic scale compensation cannot be proven")
    jsons = refs["char_json"].get(key, [])
    if not jsons:
        reasons.append("not used by any character JSON, so the on-screen size cannot be compensated automatically")
    for rel, text in refs["texts"]:
        if rel == xml_rel or rel in jsons:
            continue
        if _mentions(text, key):
            reasons.append(f"also referenced by {rel}; its scale cannot be fixed automatically")
            break
    return (not reasons), reasons, {"xml": xml_rel, "char_jsons": jsons, "warnings": warnings}
