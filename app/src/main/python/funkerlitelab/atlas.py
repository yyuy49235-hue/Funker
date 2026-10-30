"""Read-only Sparrow/TextureAtlas XML checks. Reports facts; never edits anything.

A passing bounds check only means the rectangles fit inside the image. It does NOT show that
the atlas renders correctly in game.
"""
import os
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from PIL import Image

RECT = ("x", "y", "width", "height")
FRAME = ("frameX", "frameY", "frameWidth", "frameHeight")


def resolve_image(folder: Path, name: str):
    """Find the image an atlas names. Returns (path|None, how). Tries exact, then
    space/underscore swaps, then case-insensitive. The `how` string records the evidence."""
    p = folder / name
    if p.is_file():
        return p, "exact"
    for alt in (name.replace(" ", "_"), name.replace("_", " ")):
        if alt != name and (folder / alt).is_file():
            return folder / alt, "space/underscore variant"
    try:
        lower = {e.name.lower(): e for e in os.scandir(folder) if e.is_file()}
    except OSError:
        return None, "folder unreadable"
    hit = lower.get(name.lower())
    return (Path(hit.path), "case-insensitive match (may fail on a case-sensitive device)") if hit else (None, "not found")


def check_atlas(xml_path: Path, root: Path):
    rel = str(xml_path.relative_to(root))
    out = {"xml": rel, "status": "OK", "notes": []}
    try:
        tree_root = ET.parse(xml_path).getroot()
    except Exception as e:
        out.update(status="XML_ERROR", notes=[f"{type(e).__name__}: {e}"])
        return out
    subs = [n for n in tree_root.iter() if n.tag == "SubTexture"]
    if not subs:
        out.update(status="NOT_ATLAS", notes=["no SubTexture nodes; not treated as an atlas"])
        return out
    out["frames"] = len(subs)
    out["frames_with_frame_offsets"] = sum(1 for n in subs if any(n.get(k) is not None for k in FRAME))
    name = tree_root.get("imagePath")
    if not name:
        out.update(status="NO_IMAGE_PATH", notes=["TextureAtlas has no imagePath attribute"])
        return out
    img, how = resolve_image(xml_path.parent, name)
    out["image_path_attr"] = name
    out["image_resolution"] = how
    if img is None:
        out.update(status="MISSING_IMAGE", notes=[f"{name} not found next to the XML (suspected, other lookup paths are engine-specific)"])
        return out
    try:
        with Image.open(img) as im:
            iw, ih = im.size
    except Exception as e:
        out.update(status="IMAGE_UNREADABLE", notes=[f"{type(e).__name__}: {e}"])
        return out
    out["image"], out["image_size"] = str(img.relative_to(root)), [iw, ih]
    bad, nonnum = [], []
    for n in subs:
        try:
            x, y, w, h = (float(n.get(k)) for k in RECT)
        except (TypeError, ValueError):
            nonnum.append(n.get("name"))
            continue
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > iw or y + h > ih:
            bad.append(n.get("name"))
    dup = [k for k, v in Counter(n.get("name") for n in subs).items() if v > 1]
    out["out_of_bounds"] = len(bad)
    out["non_numeric_rects"] = len(nonnum)
    out["duplicate_names"] = len(dup)
    if bad or nonnum:
        out["status"] = "CHECK_FRAMES"
        out["notes"].append(f"examples: {(bad + nonnum)[:3]}")
    if dup:
        out["notes"].append(f"duplicate frame names (may be intentional): {dup[:3]}")
    return out


def check_atlases(root):
    root = Path(root)
    results = []
    for dp, dn, fn in os.walk(root, followlinks=False):
        for n in sorted(fn):
            if n.lower().endswith(".xml"):
                p = Path(dp) / n
                if not p.is_symlink():
                    results.append(check_atlas(p, root))
    results.sort(key=lambda r: r["xml"])
    return results
