"""Stage B: user-approved downscaling of character atlases, with the matching atlas/JSON fixes."""
import io
import time
from pathlib import Path

from PIL import Image

from .atlas_scale import ScaleError, compensate_character_json, scale_sparrow_xml
from .png_optimizer import encode_verified, profile_image, read_png_chunks, _ihdr
from .references import check_compensable

PIXEL_ART_MAX_COLORS = 64
ASPECT_TOLERANCE = 0.003
MODE_LIMITS = {"balanced": {"min_scale": 0.5, "min_long_side": 2048},
               "aggressive": {"min_scale": 0.25, "min_long_side": 1024}}


def effective_factor(mode, requested):
    lim = MODE_LIMITS[mode]
    return max(lim["min_scale"], min(0.95, float(requested)))


def build_resized(root, rel_png, mode, requested_scale, refs, strip_metadata=True, max_pixels=70_000_000):
    """Return (info dict, plan|None). plan = {png_bytes, xml_rel, xml_text, json_edits{rel:text}, factor}.
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
        f_req = effective_factor(mode, requested_scale)
        nw, nh = max(1, round(w * f_req)), max(1, round(h * f_req))
        if nw >= w or nh >= h:
            info["reason"] = "resize would not reduce the image (never upscale)"
            return info, None
        fx, fy = nw / w, nh / h
        if abs(fx - fy) / max(fx, fy) > ASPECT_TOLERANCE:
            info["reason"] = f"{w}x{h} cannot be scaled to {f_req:.0%} without changing the aspect ratio"
            return info, None
        src = Image.open(io.BytesIO(raw))
        src.load()
        prof = profile_image(src, cap=PIXEL_ART_MAX_COLORS)
        if prof["colors"] is not None and not prof["partial_alpha"]:
            info["reason"] = f"pixel-art-like image ({prof['n_colors']} colors, hard alpha); not resized"
            return info, None
        work = src if src.mode in ("RGBA", "RGB", "LA", "L") else src.convert("RGBA")
        small = work.resize((nw, nh), Image.Resampling.LANCZOS)  # Pillow premultiplies alpha for RGBA/LA
        best = encode_verified(small, chunks, strip_metadata, [])
        if best is None:
            info["status"], info["reason"] = "FAILED", "resized candidate failed verification"
            return info, None
        factor = (fx + fy) / 2
        xml_text, frames = scale_sparrow_xml((root / deps["xml"]).read_bytes().decode("utf-8-sig"), fx, fy, nw, nh)
        edits = {}
        for jrel in deps["char_jsons"]:
            new_text, old_s, new_s = compensate_character_json((root / jrel).read_bytes().decode("utf-8-sig"), factor)
            edits[jrel] = new_text
            info.setdefault("scale_changes", {})[jrel] = [old_s, new_s]
        info.update(status="RESIZED", reason="ok", factor=round(factor, 6), dims_after=[nw, nh],
                    frames=frames, technique=best[1], xml=deps["xml"], duration_s=time.monotonic() - t0)
        return info, {"png_bytes": best[0], "xml_rel": deps["xml"], "xml_text": xml_text, "json_edits": edits,
                      "factor": factor}
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
