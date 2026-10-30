"""Lossless PNG optimization (stage A).

For every PNG several candidate encodings are built in memory:
  * same color type,
  * smaller color types that carry exactly the same pixels (opaque RGBA -> RGB, gray RGB -> L/LA,
    <=256 distinct RGBA colors -> palette + tRNS),
each tried with a few DEFLATE settings. A candidate is kept only if its decoded RGBA pixels are
identical to the source (compared strip by strip, low memory), dimensions match, and it is
strictly smaller. Color-affecting chunks (gAMA, cHRM, sRGB, iCCP, pHYs) are copied byte for byte.
Pure-metadata chunks (text, tIME, eXIf, bKGD...) are dropped unless strip_metadata=False.
The source file is never written by this module.
"""
import io
import os
import struct
import time
import zlib
from dataclasses import dataclass, field

from PIL import Image

try:
    import numpy as np
except ImportError:  # palette/gray detection are skipped without numpy
    np = None

CRITICAL = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS"}
RAW_KEEP = [b"gAMA", b"cHRM", b"sRGB", b"iCCP", b"pHYs"]       # copied byte for byte
MODE_BOUND = {b"sBIT"}                                          # copied only if color type unchanged
TEXTLIKE = {b"tEXt", b"zTXt", b"iTXt", b"tIME", b"eXIf"}        # dropped unless strip_metadata=False
DROP_ALWAYS = {b"bKGD", b"hIST", b"sPLT"}                       # tied to the old color type
KNOWN = CRITICAL | set(RAW_KEEP) | MODE_BOUND | TEXTLIKE | DROP_ALWAYS
SUPPORTED_MODES = {"1", "L", "LA", "P", "RGB", "RGBA"}
BYTES_PER_PIXEL = {"1": 1, "L": 1, "P": 1, "LA": 2, "RGB": 3, "RGBA": 4}
STRIP_ROWS = 256
FAST_ABOVE_PIXELS = 16_000_000
SETTINGS = [dict(optimize=True, compress_level=9),
            dict(compress_level=9, compress_type=1),   # zlib Z_FILTERED
            dict(compress_level=9, compress_type=3)]   # zlib Z_RLE


@dataclass
class ImageResult:
    rel_path: str
    status: str  # SUCCESS | SKIPPED | FAILED
    reason: str = ""
    original_size: int = 0
    candidate_size: int = 0
    final_size: int = 0
    applied: bool = False
    dims_before: tuple = ()
    dims_after: tuple = ()
    pixel_verified: bool = False
    est_decoded_bytes: int = 0  # theoretical w*h*bytes-per-pixel, NOT real game memory
    technique: str = ""
    mode_before: str = ""
    mode_after: str = ""
    stripped_chunks: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    duration_s: float = 0.0

    @property
    def bytes_saved(self):
        return self.original_size - self.final_size


# ---------------------------------------------------------------- raw PNG helpers
def read_png_chunks(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG signature")
    pos, out = 8, []
    while pos + 8 <= len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        t = data[pos + 4:pos + 8]
        out.append((t, data[pos + 8:pos + 8 + n]))
        pos += 12 + n
        if t == b"IEND":
            break
    return out


def _chunk(t, d):
    return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)


def _serialize(chunks):
    return b"\x89PNG\r\n\x1a\n" + b"".join(_chunk(t, d) for t, d in chunks)


def _ihdr(chunks):
    w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", dict(chunks)[b"IHDR"])
    return w, h, depth, ctype


# ---------------------------------------------------------------- pixel helpers
def _strips(im):
    w, h = im.size
    for y in range(0, h, STRIP_ROWS):
        yield im.crop((0, y, w, min(h, y + STRIP_ROWS)))


def rgba_equal(a, b):
    """True if both images decode to identical RGBA pixels (strip by strip)."""
    if a.size != b.size:
        return False
    w, h = a.size
    for y in range(0, h, STRIP_ROWS):
        box = (0, y, w, min(h, y + STRIP_ROWS))
        if a.crop(box).convert("RGBA").tobytes() != b.crop(box).convert("RGBA").tobytes():
            return False
    return True


def profile_image(im, cap=256):
    """One pass over the pixels: distinct RGBA colors (None if > cap), fully opaque?, gray?, partial alpha?"""
    if np is None:
        return {"colors": None, "n_colors": None, "opaque": False, "gray": False, "partial_alpha": True}
    colors, over, opaque, gray, partial = set(), False, True, True, False
    for s in _strips(im):
        a = np.asarray(s.convert("RGBA"))
        al = a[..., 3]
        if opaque and not (al == 255).all():
            opaque = False
        if not partial and ((al != 0) & (al != 255)).any():
            partial = True
        if gray and not ((a[..., 0] == a[..., 1]).all() and (a[..., 1] == a[..., 2]).all()):
            gray = False
        if not over:
            u = np.unique(np.ascontiguousarray(a).view("<u4").reshape(-1))
            colors.update(u.tolist())
            if len(colors) > cap:
                over, colors = True, set()
    return {"colors": None if over else sorted(colors), "n_colors": None if over else len(colors),
            "opaque": opaque, "gray": gray, "partial_alpha": partial}


def _palette_image(im, colors):
    """Build a P-mode image with the exact RGBA colors. Returns (image, transparency bytes|None)."""
    pal = sorted(colors, key=lambda v: (((v >> 24) & 255) == 255, v))  # non-opaque entries first
    order = {v: i for i, v in enumerate(pal)}
    ks = np.array(sorted(pal), dtype="<u4")
    to_index = np.array([order[v] for v in sorted(pal)], dtype=np.uint8)
    out = bytearray()
    for s in _strips(im):
        a32 = np.ascontiguousarray(np.asarray(s.convert("RGBA"))).view("<u4").reshape(-1)
        out += to_index[np.searchsorted(ks, a32)].tobytes()
    p = Image.frombytes("P", im.size, bytes(out))
    flat = []
    for v in pal:
        flat += [v & 255, (v >> 8) & 255, (v >> 16) & 255]
    p.putpalette(flat)
    alphas = [(v >> 24) & 255 for v in pal]
    while alphas and alphas[-1] == 255:
        alphas.pop()
    return p, (bytes(alphas) if alphas else None)


def _encode_raw(im, transparency, fast):
    """Best of several DEFLATE settings. `im` must carry no metadata (info is cleared)."""
    im = im.copy()
    im.info = {}
    best = None
    for opts in (SETTINGS[:1] if fast else SETTINGS):
        kw = dict(format="PNG", **opts)
        if transparency is not None:
            kw["transparency"] = transparency
        buf = io.BytesIO()
        im.save(buf, **kw)
        data = buf.getvalue()
        if best is None or len(data) < len(best):
            best = data
    return best


def _splice(png, src_chunks, mode_changed, strip_metadata):
    """Put the source's preserved ancillary chunks right after IHDR of the new PNG."""
    new = read_png_chunks(png)
    keep, dropped = [], []
    for t, d in src_chunks:
        if t in RAW_KEEP or (t in MODE_BOUND and not mode_changed) or (t in TEXTLIKE and not strip_metadata):
            keep.append((t, d))
        elif t in TEXTLIKE or t in DROP_ALWAYS or t in MODE_BOUND:
            dropped.append(t.decode())
    return _serialize([new[0]] + keep + new[1:]), sorted(set(dropped))


# ---------------------------------------------------------------- main entry
def _variants(src, prof, has_iccp):
    """Yield (name, image, transparency, mode_changed). Cheap ones first."""
    m = src.mode
    trans = src.info.get("transparency")
    yield "re-encode", src, trans if m in ("P", "L", "RGB") else None, False
    if np is None or (trans is not None and m in ("RGB", "L", "P")):
        return
    if m == "RGBA" and prof["opaque"]:
        yield "drop-alpha", src.convert("RGB"), None, True
    if m in ("RGB", "RGBA") and prof["gray"] and not has_iccp:
        yield ("gray" if prof["opaque"] else "gray+alpha"), src.convert("L" if prof["opaque"] else "LA"), None, True
    if m == "LA" and prof["opaque"]:
        yield "drop-alpha", src.convert("L"), None, True
    if m in ("RGB", "RGBA") and prof["colors"] is not None:
        p, t = _palette_image(src, prof["colors"])
        yield f"palette({prof['n_colors']} colors)", p, t, True


def encode_verified(src, src_chunks, strip_metadata, warnings):
    """Best verified candidate for an already-decoded image: (bytes, technique, mode, dropped_chunks) or None.
    Verification = identical RGBA pixels against `src` (which may itself be a resized image)."""
    types = {t for t, _ in src_chunks}
    w, h = src.size
    prof = profile_image(src) if src.mode in ("RGB", "RGBA", "LA") else {"colors": None, "opaque": False, "gray": False}
    fast = w * h > FAST_ABOVE_PIXELS
    has_iccp = b"iCCP" in types
    best = None
    for name, img, trans, changed in _variants(src, prof, has_iccp):
        data, dropped = _splice(_encode_raw(img, trans, fast), src_chunks, changed, strip_metadata)
        if best is not None and len(data) >= len(best[0]):
            continue
        cand = Image.open(io.BytesIO(data))
        cand.load()
        if cand.size == src.size and rgba_equal(src, cand):
            best = (data, name, cand.mode, dropped)
        else:
            warnings.append(f"variant '{name}' rejected: pixels differ")
    return best


def build_candidate(path, max_pixels=70_000_000, strip_metadata=True):
    """Return (ImageResult, candidate_bytes|None). Never modifies `path`."""
    t0 = time.monotonic()
    res = ImageResult(rel_path=str(path), status="SKIPPED")
    try:
        res.original_size = os.path.getsize(path)
        with open(path, "rb") as f:
            raw = f.read()
        try:
            src_chunks = read_png_chunks(raw)
        except ValueError as e:
            res.status, res.reason = "FAILED", f"unreadable PNG: {e}"
            return res, None
        types = {t for t, _ in src_chunks}
        if b"acTL" in types:
            res.reason = "animated PNG not supported"
            return res, None
        w, h, depth, _ = _ihdr(src_chunks)
        if depth > 8:
            res.reason = f"{depth}-bit PNG would be reduced to 8-bit by the encoder; skipped"
            return res, None
        unknown = sorted(t.decode(errors="replace") for t in types - KNOWN)
        if unknown:
            res.reason = f"unknown chunks that cannot be preserved: {unknown}; skipped"
            return res, None
        try:
            src = Image.open(io.BytesIO(raw))
        except Image.DecompressionBombError:
            res.reason = "image exceeds Pillow decompression-bomb limit; skipped"
            return res, None
        res.dims_before = src.size
        if w * h > max_pixels:
            res.reason = f"pixel count {w*h} exceeds limit {max_pixels}"
            return res, None
        if src.mode not in SUPPORTED_MODES:
            res.reason = f"unsupported mode {src.mode}"
            return res, None
        res.mode_before = src.mode
        res.est_decoded_bytes = w * h * BYTES_PER_PIXEL[src.mode]
        src.load()
        best = encode_verified(src, src_chunks, strip_metadata, res.warnings)
        if best is None:
            res.status, res.reason = "FAILED", "no candidate passed pixel verification"
            return res, None
        data, res.technique, res.mode_after, res.stripped_chunks = best
        res.candidate_size, res.dims_after, res.pixel_verified = len(data), (w, h), True
        if res.candidate_size >= res.original_size:
            res.reason = "candidate not strictly smaller; discarded"
            return res, None
        res.status, res.reason = "SUCCESS", "eligible"
        return res, data
    except MemoryError:
        res.status, res.reason = "FAILED", "out of memory while decoding"
        return res, None
    except Exception as e:
        res.status, res.reason = "FAILED", f"{type(e).__name__}: {e}"
        return res, None
    finally:
        res.duration_s = time.monotonic() - t0
        res.final_size = res.original_size
