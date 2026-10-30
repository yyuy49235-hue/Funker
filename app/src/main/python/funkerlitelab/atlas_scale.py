"""Exact, text-preserving edits needed when an atlas image is downscaled.

scale_sparrow_xml(): scales every SubTexture rectangle AND its frame offsets (frameX/frameY/
frameWidth/frameHeight). Rectangles are scaled by their edges (round(x), round(x+w)) so neighbouring
frames never gain gaps or overlaps. Only the numbers change; all other text is kept byte for byte.

compensate_character_json(): the game draws a sprite at (frame size x scale). If the atlas shrinks by
factor f, the character's "scale" must grow by 1/f to keep the same on-screen size. Only the "scale"
value is changed (or inserted); the result is re-parsed to prove nothing else differs.
"""
import json
import math
import re
import xml.etree.ElementTree as ET

RECT_ATTRS = ("x", "y", "width", "height")
FRAME_ATTRS = ("frameX", "frameY", "frameWidth", "frameHeight")
_TAG = re.compile(r"<SubTexture\b[^>]*>", re.S)
_ATTR = re.compile(r"""\b(x|y|width|height|frameX|frameY|frameWidth|frameHeight)(\s*=\s*)(["'])(-?[0-9]*\.?[0-9]+)\3""")


class ScaleError(Exception):
    pass


def _r(v):
    return int(math.floor(v + 0.5))


def scale_sparrow_xml(text, fx, fy, new_w, new_h):
    """Return (new_text, frame_count). Raises ScaleError if the result is not provably consistent."""
    before = [n for n in ET.fromstring(text.encode("utf-8")).iter() if n.tag == "SubTexture"]
    count = 0

    def fix_tag(m):
        nonlocal count
        tag = m.group(0)
        vals = {a.group(1): float(a.group(4)) for a in _ATTR.finditer(tag)}
        if not all(k in vals for k in RECT_ATTRS):
            raise ScaleError("SubTexture without x/y/width/height")
        x0, x1 = _r(vals["x"] * fx), _r((vals["x"] + vals["width"]) * fx)
        y0, y1 = _r(vals["y"] * fy), _r((vals["y"] + vals["height"]) * fy)
        new = {"x": x0, "y": y0, "width": max(1, x1 - x0), "height": max(1, y1 - y0)}
        if "frameX" in vals:
            new["frameX"] = _r(vals["frameX"] * fx)
        if "frameY" in vals:
            new["frameY"] = _r(vals["frameY"] * fy)
        if "frameWidth" in vals:
            new["frameWidth"] = max(1, _r(vals["frameWidth"] * fx))
        if "frameHeight" in vals:
            new["frameHeight"] = max(1, _r(vals["frameHeight"] * fy))
        count += 1
        return _ATTR.sub(lambda a: f"{a.group(1)}{a.group(2)}{a.group(3)}{new[a.group(1)]}{a.group(3)}", tag)

    new_text = _TAG.sub(fix_tag, text)
    after = [n for n in ET.fromstring(new_text.encode("utf-8")).iter() if n.tag == "SubTexture"]
    if len(after) != len(before) or [n.get("name") for n in after] != [n.get("name") for n in before]:
        raise ScaleError("frame names/count changed")
    for n in after:
        x, y, w, h = (float(n.get(k)) for k in RECT_ATTRS)
        if x < 0 or y < 0 or w < 1 or h < 1 or x + w > new_w or y + h > new_h:
            raise ScaleError(f"frame {n.get('name')!r} falls outside the resized image")
    return new_text, count


_SCALE = re.compile(r'("scale"\s*:\s*)(-?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)')


def compensate_character_json(text, factor):
    """Return (new_text, old_scale, new_scale). `factor` = resized/original (e.g. 0.5)."""
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ScaleError(f"character JSON does not parse: {e}")
    if not isinstance(data, dict):
        raise ScaleError("character JSON is not an object")
    old = data.get("scale", 1)
    if isinstance(old, bool) or not isinstance(old, (int, float)):
        raise ScaleError('"scale" is not a number')
    new = round(old / factor, 6)
    new_lit = repr(float(new)) if new != int(new) else str(int(new)) + ".0"
    hits = _SCALE.findall(text)
    if "scale" in data:
        if len(hits) != 1:
            raise ScaleError('ambiguous "scale" key (found %d textual matches)' % len(hits))
        new_text = _SCALE.sub(lambda m: m.group(1) + new_lit, text, count=1)
    else:
        i = text.index("{")
        new_text = text[:i + 1] + f'\n\t"scale": {new_lit},' + text[i + 1:]
    check = json.loads(new_text)
    expect = dict(data)
    expect["scale"] = new
    if check != expect:
        raise ScaleError("JSON changed in more than the scale value; edit rejected")
    return new_text, old, new
