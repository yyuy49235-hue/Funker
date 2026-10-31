"""Atlas format adapters. Each declares what it recognizes, what it may modify and its limits.
Unknown formats are never forced through an adapter: they fall back to 'preserve untouched'."""
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path


class SparrowXml:
    name = "sparrow-xml"
    engines = "Psych Engine (all versions seen), base FNF, most forks"
    evidence = "XML next to the PNG with SubTexture nodes and an imagePath attribute"
    can_scale = True                      # atlas_scale.scale_sparrow_xml + character JSON scale fix
    modifies = ["xml: x,y,width,height,frameX,frameY,frameWidth,frameHeight", "character json: scale"]
    limits = "rotated frames (rotated=\"true\") are not handled; such atlases are refused"

    @staticmethod
    def detect(root, rel_png):
        x = Path(root) / Path(rel_png).with_suffix(".xml")
        if not x.is_file():
            return None
        try:
            r = ET.parse(x).getroot()
        except ET.ParseError:
            return {"found": True, "detail": "XML next to image does not parse"}
        subs = [n for n in r.iter() if n.tag == "SubTexture"]
        if not subs:
            return None
        if any(n.get("rotated", "false").lower() == "true" for n in subs):
            return {"found": True, "detail": "frames with rotated=true", "refuse": True}
        return {"found": True}


class PackerTxt:
    name = "packer-txt"
    engines = "Flixel/Psych (loaded via getPackerAtlas)"
    evidence = "TXT next to the PNG with lines 'name = x y w h'"
    can_scale = False
    modifies = []
    limits = "recognized only; resizing is refused because no scaling code/tests exist for it"
    _LINE = re.compile(r"^\s*\S.*=\s*-?\d+\s+-?\d+\s+\d+\s+\d+\s*$")

    @staticmethod
    def detect(root, rel_png):
        t = Path(root) / Path(rel_png).with_suffix(".txt")
        if not t.is_file():
            return None
        try:
            lines = [l for l in t.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()][:20]
        except OSError:
            return None
        return {"found": True} if lines and all(PackerTxt._LINE.match(l) for l in lines) else None


class JsonAtlas:
    name = "json-atlas"
    engines = "Starling/TexturePacker JSON (frames + meta)"
    evidence = "JSON next to the PNG containing 'frames' and 'meta'"
    can_scale = False
    modifies = []
    limits = "recognized only; resizing refused"

    @staticmethod
    def detect(root, rel_png):
        j = Path(root) / Path(rel_png).with_suffix(".json")
        if not j.is_file():
            return None
        try:
            d = json.loads(j.read_text(encoding="utf-8-sig"))
        except (ValueError, OSError):
            return None
        return {"found": True} if isinstance(d, dict) and "frames" in d and "meta" in d else None


class AnimateAtlas:
    name = "animate-atlas"
    engines = "Adobe Animate texture atlas (Animation.json + spritemap)"
    evidence = "a folder named like the image containing Animation.json"
    can_scale = False
    modifies = []
    limits = "recognized only; resizing refused"

    @staticmethod
    def detect(root, rel_png):
        d = Path(root) / Path(rel_png).with_suffix("")
        return {"found": True} if (d / "Animation.json").is_file() else None


ADAPTERS = [SparrowXml, PackerTxt, JsonAtlas, AnimateAtlas]


def detect_atlas(root, rel_png):
    """Return (adapter|None, info). First match wins; None means 'plain image or unknown format'."""
    for a in ADAPTERS:
        info = a.detect(root, rel_png)
        if info:
            return a, info
    return None, {}


def describe_adapters():
    return [{"name": a.name, "engines": a.engines, "evidence": a.evidence, "can_resize": a.can_scale,
             "modifies": a.modifies, "limits": a.limits} for a in ADAPTERS]
