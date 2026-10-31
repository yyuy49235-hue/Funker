"""Stage B: user-approved downscaling of character atlases, with the matching atlas/JSON fixes.

scale="auto" (the default): the factor is chosen PER IMAGE from measurements, never a fixed percentage:
  * candidate factors come from a ladder limited by the mode (balanced >= 50%, aggressive >= 25%),
  * a factor is rejected if the new size changes the aspect ratio, if atlas frame edges would land on
    fractional pixels too often (mean alignment error), or if the SAMPLED detail loss is above the mode limit,
  * the smallest factor that passes all three is used; if none passes the image is left alone.
Detail loss is an estimate: a few content-rich 512px tiles are shrunk and enlarged back and compared with the original.
"""
import io
import re
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from .atlas_scale import ScaleError, compensate_character_json, decode_keep, encode_keep, scale_sparrow_xml
from .png_optimizer import encode_verified, profile_image, read_png_chunks, _ihdr
from .references import check_compensable

PIXEL_ART_MAX_COLORS = 64
ASPECT_TOLERANCE = 0.003
MODE_LIMITS = {"balanced": {"min_scale": 0.5, "min_long_side": 2048, "max_loss": 2.0, "max_align": 0.30},
               "aggressive": {"min_scale": 0.25, "min_long_side": 1024, "max_loss": 5.0, "max_align": 0.35}}
LADDER = [0.25, 0.33, 0.4, 0.5, 0.6, 0.66, 0.75, 0.8, 0.9]
TILE = 512
_ATTR = re.compile(r"""\b(x|y|width|height)\s*=\s*(["'])(-?[0-9]*\.?[0-9]+)\2""")


def effective_factor(mode, requested):
    lim = MODE_LIMITS[mode]
    return max(lim["min_scale"], min(0.95, float(requested)))


def _sample_tiles(im, n=4):
    """Up to n content-rich tiles (by variance, with visible pixels). Whole image if it is small."""
    w, h = im.size
    if w <= TILE and h <= TILE:
        return [im.convert("RGBA")]
    xs = [int(i * (w - TILE) / 5) for i in range(6)] if w > TILE else [0]
    ys = [int(i * (h - TILE) / 5) for i in range(6)] if h > TILE else [0]
    scored = []
    for y in ys:
        for x in xs:
            t = im.crop((x, y, min(w, x + TILE), min(h, y + TILE))).convert("RGBA")
            a = ImageStat.Stat(t.getchannel("A"))
            if a.mean[0] < 25:                       # mostly transparent: tells us nothing about detail
                continue
            scored.append((ImageStat.Stat(t.convert("L")).var[0], x, y, t))
    scored.sort(key=lambda s: -s[0])
    return [s[3] for s in scored[:n]] or [im.crop((0, 0, min(w, TILE), min(h, TILE))).convert("RGBA")]


def detail_loss(tiles, factor):
    """Mean absolute error (0..255, premultiplied RGBA) after shrinking by `factor` and enlarging back."""
    total = 0.0
    for t in tiles:
        w, h = t.size
        small = t.resize((max(1, round(w * factor)), max(1, round(h * factor))), Image.Resampling.LANCZOS)
        back = small.resize((w, h), Image.Resampling.LANCZOS)
        diff = ImageChops.difference(t.convert("RGBa"), back.convert("RGBa"))
        total += sum(ImageStat.Stat(diff).mean) / 4.0
    return total / len(tiles)


def alignment_error(xml_text, fx, fy):
    """Mean distance (px) between the exact scaled frame edges and the nearest whole pixel."""
    errs = []
    for tag in re.findall(r"<SubTexture\b[^>]*>", xml_text, re.S):
        v = {m.group(1): float(m.group(3)) for m in _ATTR.finditer(tag)}
        if len(v) < 4:
            continue
        for k, f in (("x", fx), ("y", fy)):
            for e in (v[k] * f, (v[k] + v["width" if k == "x" else "height"]) * f):
                errs.append(abs(e - round(e)))
    return sum(errs) / len(errs) if errs else 0.0


def choose_factor(mode, src, xml_text):
    """Return (factor|None, details). Tries the ladder from the smallest allowed factor upwards."""
    lim = MODE_LIMITS[mode]
    w, h = src.size
    tiles = _sample_tiles(src)
    tested = []
    for f in LADDER:
        if f < lim["min_scale"] - 1e-9:
            continue
        nw, nh = max(1, round(w * f)), max(1, round(h * f))
        if nw >= w or nh >= h:
            continue
        fx, fy = nw / w, nh / h
        row = {"factor": f, "size": [nw, nh]}
        if abs(fx - fy) / max(fx, fy) > ASPECT_TOLERANCE:
            row["rejected"] = "aspect ratio"
        else:
            row["align_px"] = round(alignment_error(xml_text, fx, fy), 3)
            if row["align_px"] > lim["max_align"]:
                row["rejected"] = "frame edges land on fractional pixels"
            else:
                row["loss"] = round(detail_loss(tiles, f), 3)
                if row["loss"] > lim["max_loss"]:
                    row["rejected"] = "estimated detail loss too high"
        tested.append(row)
        if "rejected" not in row:
            return f, {"chosen": f, "tested": tested, "loss_limit": lim["max_loss"], "estimate": "sampled tiles"}
    return None, {"chosen": None, "tested": tested, "loss_limit": lim["max_loss"]}


def build_resized(root, rel_png, mode, requested_scale, refs, strip_metadata=True, max_pixels=70_000_000):
    """Return (info dict, plan|None). plan = {png_bytes, xml_rel, xml_bytes, json_edits{rel:bytes}, factor}.
    Never writes anything. info['status'] is RESIZED or SKIPPED with info['reason']."""
    t0 = time.monotonic()
    root = Path(root)
    info = {"rel_path": rel_png, "status": "SKIPPED", "reason": "", "factor": None}
    path = root / rel_png
    try:
        lim = MODE_LIMITS[mode]
        raw = path.read_bytes()
        chunks = read_png_chunks(raw)
        w, h, depth, _ = _ihdr(chunks)
        info["dims_before"] = [w, h]
        if depth > 8:
            info["reason"] = f"{depth}-bit PNG not supported"
            return info, None
        if max(w, h) < lim["min_long_side"]:
            info["reason"] = f"longest side {max(w, h)}px is below the {mode} threshold ({lim['min_long_side']}px)"
            return info, None
        if w * h > max_pixels:
            info["reason"] = "pixel count exceeds the configured limit"
            return info, None
        ok, reasons, deps = check_compensable(root, rel_png, refs)
        if not ok:
            info["reason"] = "; ".join(reasons)
            info["manual_fix_needed"] = True
            return info, None
        src = Image.open(io.BytesIO(raw))
        src.load()
        prof = profile_image(src, cap=PIXEL_ART_MAX_COLORS)
        if prof["colors"] is not None and not prof["partial_alpha"]:
            info["reason"] = f"pixel-art-like image ({prof['n_colors']} colors, hard alpha); not resized"
            return info, None
        xml_src, xml_how = decode_keep((root / deps["xml"]).read_bytes(), True)
        if isinstance(requested_scale, str) and requested_scale.lower() == "auto":
            f_req, details = choose_factor(mode, src, xml_src)
            info["auto"] = details
            if f_req is None:
                why = {r.get("rejected") for r in details["tested"]}
                info["reason"] = "no safe factor found automatically (" + ", ".join(sorted(x for x in why if x)) + ")"
                return info, None
        else:
            f_req = effective_factor(mode, requested_scale)
        nw, nh = max(1, round(w * f_req)), max(1, round(h * f_req))
        if nw >= w or nh >= h:
            info["reason"] = "resize would not reduce the image (never upscale)"
            return info, None
        fx, fy = nw / w, nh / h
        if abs(fx - fy) / max(fx, fy) > ASPECT_TOLERANCE:
            info["reason"] = f"{w}x{h} cannot be scaled to {f_req:.0%} without changing the aspect ratio"
            return info, None
        work = src if src.mode in ("RGBA", "RGB", "LA", "L") else src.convert("RGBA")
        small = work.resize((nw, nh), Image.Resampling.LANCZOS)  # Pillow premultiplies alpha for RGBA/LA
        best = encode_verified(small, chunks, strip_metadata, [])
        if best is None:
            info["status"], info["reason"] = "FAILED", "resized candidate failed verification"
            return info, None
        factor = (fx + fy) / 2
        xml_text, frames = scale_sparrow_xml(xml_src, fx, fy, nw, nh)
        edits = {}
        for jrel in deps["char_jsons"]:
            j_src, j_how = decode_keep((root / jrel).read_bytes(), False)
            new_text, old_s, new_s = compensate_character_json(j_src, factor)
            edits[jrel] = encode_keep(new_text, j_how)
            info.setdefault("scale_changes", {})[jrel] = [old_s, new_s]
        if deps.get("warnings"):
            info["warnings"] = deps["warnings"]
        info.update(status="RESIZED", reason="ok", factor=round(factor, 6), dims_after=[nw, nh],
                    frames=frames, technique=best[1], xml=deps["xml"], duration_s=time.monotonic() - t0)
        return info, {"png_bytes": best[0], "xml_rel": deps["xml"], "xml_bytes": encode_keep(xml_text, xml_how),
                      "json_edits": edits, "factor": factor}
    except ScaleError as e:
        info["reason"] = f"scale fix not provable: {e}"
        info["manual_fix_needed"] = True
        return info, None
    except MemoryError:
        info["status"], info["reason"] = "FAILED", "out of memory"
        return info, None
    except Exception as e:
        info["status"], info["reason"] = "FAILED", f"{type(e).__name__}: {e}"
        return info, None
