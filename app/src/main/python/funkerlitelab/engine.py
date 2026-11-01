"""Mod optimizer.

Design rules:
- The input folder is only ever read. All output goes to a new ZIP.
- Lossless PNG recompression is applied only if the result is smaller AND pixel-identical.
- Resizing is applied only to character atlases where every relation can be updated and
  checked: exactly one Sparrow XML atlas, at least one characters/*.json, and no other text
  file (lua/json/hx/...) mentioning the image. Anything else is left at original size.
- Files the engine does not understand are copied unchanged.
"""
import json
import os
import re
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET

from PIL import Image, ImageChops

Image.MAX_IMAGE_PIXELS = None  # we enforce our own limit below

# max_dim: longest image side allowed after optimization (None = never resize)
# repack: trim/dedupe/re-pack Sparrow atlases (lossless for rendering, scale unchanged).
# Only enabled for the two strongest presets; light/balanced behave exactly as before.
LEVELS = {
    "light": {"max_dim": None, "repack": False},
    "balanced": {"max_dim": 2048, "repack": False},
    "strong": {"max_dim": 1536, "repack": True},
    "maximum": {"max_dim": 1024, "repack": True},
}
MAX_PIXELS = 24_000_000
TEXT_EXT = {".lua", ".json", ".hx", ".hscript", ".txt", ".xml", ".csv"}
STORE_EXT = {".png", ".ogg", ".mp3", ".mp4", ".webm", ".jpg", ".jpeg", ".zip", ".mov"}
ATLAS_ATTRS_X = ("x", "width", "frameX", "frameWidth")
ATLAS_ATTRS_Y = ("y", "height", "frameY", "frameHeight")
MAX_DETAILS = 500


class Cancelled(Exception):
    pass


def _noop(stage, done, total, name):
    return True


def scan(root):
    """Return (files, empty_dirs). files: list of (rel_posix, abs_path, size)."""
    files, empty_dirs, notes = [], [], []
    for dp, dn, fn in os.walk(root):
        keep = []
        for d in sorted(dn):
            if os.path.islink(os.path.join(dp, d)):
                notes.append("symlinked folder not followed: " + d)
            else:
                keep.append(d)
        dn[:] = keep
        rel_dir = os.path.relpath(dp, root).replace(os.sep, "/")
        if not fn and not dn and rel_dir != ".":
            empty_dirs.append(rel_dir)
        for f in sorted(fn):
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            files.append((rel, p, os.path.getsize(p)))
    return files, empty_dirs, notes


def _file_mentions(path, pattern, overlap):
    """Chunked case-insensitive regex search; never loads a whole file."""
    prev = b""
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                return False
            data = (prev + chunk).lower()
            if pattern.search(data):
                return True
            prev = data[-overlap:] if overlap else b""


def _build_maps(files, abs_of):
    atlas_map, char_map = {}, {}
    for rel, p, size in files:
        low = rel.lower()
        if low.endswith(".xml") and size <= 50 * 1024 * 1024:
            try:
                for _, el in ET.iterparse(p, events=("start",)):
                    tag = el.tag.split("}")[-1]
                    ip = el.attrib.get("imagePath")
                    if tag == "TextureAtlas" and ip:
                        d = os.path.dirname(rel)
                        img = os.path.normpath(os.path.join(d, ip)).replace(os.sep, "/")
                        atlas_map.setdefault(img.lower(), []).append(rel)
                    break
            except Exception:
                pass
        elif low.endswith(".json") and low.startswith("characters/") and size <= 2 * 1024 * 1024:
            try:
                with open(p, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("image"), str):
                    key = ("images/" + data["image"] + ".png").lower()
                    char_map.setdefault(key, []).append(rel)
            except Exception:
                pass
    return atlas_map, char_map


def _lossless(src, dst):
    """Try lossless re-encode. Returns (ok, reason). Writes dst only on ok."""
    im = Image.open(src)
    im.load()
    if getattr(im, "n_frames", 1) > 1:
        return False, "animated PNG left unchanged"
    if im.mode not in ("1", "L", "LA", "P", "RGB", "RGBA"):
        return False, "unsupported PNG mode " + im.mode
    kw = {"optimize": True}
    if im.info.get("transparency") is not None and im.mode in ("1", "L", "P", "RGB"):
        kw["transparency"] = im.info["transparency"]
    if im.info.get("icc_profile"):
        kw["icc_profile"] = im.info["icc_profile"]
    tmp = dst + ".try"
    im.save(tmp, "PNG", **kw)
    if os.path.getsize(tmp) >= os.path.getsize(src):
        os.remove(tmp)
        return False, "no smaller lossless version exists"
    im2 = Image.open(tmp)
    im2.load()
    same = im.size == im2.size
    if same:
        if im.mode == im2.mode and im.mode != "P":
            same = ImageChops.difference(im, im2).getbbox() is None
        else:
            same = ImageChops.difference(im.convert("RGBA"), im2.convert("RGBA")).getbbox() is None
    if not same:
        os.remove(tmp)
        return False, "re-encoded image was not pixel-identical, kept original"
    os.replace(tmp, dst)
    return True, ""


def _plan_resize(rel, size, max_dim, atlas_map, char_map, files, abs_of, xml_bytes=None):
    """Return (ok, reason, plan). plan holds everything needed to apply the resize."""
    w, h = size
    key = rel.lower()
    xmls = atlas_map.get(key, [])
    if len(xmls) != 1:
        return False, "not resized: needs exactly one atlas XML (found %d)" % len(xmls), None
    jsons = char_map.get(key, [])
    if not jsons:
        return False, "not resized: no character JSON to compensate on-screen size", None
    ref = rel[len("images/"):-4].lower() if key.startswith("images/") else None
    if ref is None:
        return False, "not resized: image is outside images/", None
    pat = re.compile(rb"(?<![a-z0-9_\-])" + re.escape(ref.encode()) + rb"(?![a-z0-9_\-])")
    own = set(jsons) | {xmls[0]}
    for orel, op, osz in files:
        if orel in own or os.path.splitext(orel)[1].lower() not in TEXT_EXT:
            continue
        if _file_mentions(op, pat, len(ref) + 2):
            return False, "not resized: also referenced by " + orel, None
    s = min(1.0, max_dim / float(max(w, h)))
    nw, nh = max(1, round(w * s)), max(1, round(h * s))
    fx, fy = nw / float(w), nh / float(h)
    if abs(fx - fy) / fx > 0.01:
        return False, "not resized: aspect ratio would drift", None
    # atlas XML
    xp = abs_of[xmls[0]]
    try:
        tree = ET.ElementTree(ET.fromstring(xml_bytes)) if xml_bytes is not None else ET.parse(xp)
    except Exception as e:
        return False, "not resized: atlas XML unreadable (%s)" % type(e).__name__, None
    n = 0
    for el in tree.getroot().iter():
        if el.tag.split("}")[-1] != "SubTexture":
            continue
        n += 1
        for a, f in [(a, fx) for a in ATLAS_ATTRS_X] + [(a, fy) for a in ATLAS_ATTRS_Y]:
            if a in el.attrib:
                try:
                    el.set(a, str(int(round(float(el.attrib[a]) * f))))
                except ValueError:
                    return False, "not resized: non-numeric atlas value", None
        if "x" in el.attrib and "width" in el.attrib:
            if int(el.attrib["x"]) + int(el.attrib["width"]) > nw or int(el.attrib["y"]) + int(el.attrib["height"]) > nh:
                el.set("width", str(max(1, min(int(el.attrib["width"]), nw - int(el.attrib["x"])))))
                el.set("height", str(max(1, min(int(el.attrib["height"]), nh - int(el.attrib["y"])))))
    if n == 0:
        return False, "not resized: atlas XML has no SubTexture entries", None
    # character JSONs
    jdata = {}
    inv = w / float(nw)
    for jr in jsons:
        try:
            with open(abs_of[jr], "r", encoding="utf-8-sig") as f:
                d = json.load(f)
            old = d.get("scale", 1)
            if isinstance(old, bool) or not isinstance(old, (int, float)):
                return False, "not resized: non-numeric scale in " + jr, None
            d["scale"] = round(old * inv, 4)
            jdata[jr] = json.dumps(d, indent=2, ensure_ascii=False).encode("utf-8")
        except Exception as e:
            return False, "not resized: cannot update %s (%s)" % (jr, type(e).__name__), None
    import io
    buf = io.BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    plan = {"nw": nw, "nh": nh, "xml_rel": xmls[0], "xml": buf.getvalue(), "jsons": jdata,
            "factor": round(fx, 4)}
    return True, "", plan


def _resize_save(src, dst, nw, nh):
    im = Image.open(src)
    im.load()
    mode = im.mode
    if mode not in ("L", "LA", "P", "RGB", "RGBA"):
        raise ValueError("unsupported mode " + mode)
    if mode == "P":
        im = im.convert("RGBA")
    out = im.resize((nw, nh), Image.LANCZOS)
    del im
    out.save(dst, "PNG", optimize=True)
    chk = Image.open(dst)
    chk.verify()
    return os.path.getsize(dst)


def _tag(el):
    return el.tag.split("}")[-1]


def _num(el, key, default=None):
    v = el.attrib.get(key)
    if v is None:
        return default
    f = float(v)
    if f != int(f):
        raise ValueError("non-integer value for " + key)
    return int(f)


def _pack_shelf(items, pad, limit):
    """items: [(id, w, h)]. Shelf packing, tallest first. Returns (pos, width, height)."""
    x = y = shelf = maxw = 0
    pos = {}
    for i, w, h in sorted(items, key=lambda t: (-t[2], -t[1])):
        if x > 0 and x + w > limit:
            y += shelf + pad
            x = shelf = 0
        pos[i] = (x, y)
        x += w + pad
        shelf = max(shelf, h)
        maxw = max(maxw, x - pad)
    return pos, maxw, y + shelf


def _repack(src, xml_path, dst, pad=2):
    """Trim transparent borders, merge pixel-identical frames, re-pack tighter.

    Rendering is unchanged: frame names, order, source sizes and on-screen offsets are kept
    (frameX/frameY/frameWidth/frameHeight are rewritten to compensate for trimming) and the
    texture scale is untouched. Returns (ok, reason, info). Writes dst only on success.
    """
    import hashlib
    try:
        tree = ET.parse(xml_path)
    except Exception as e:
        return False, "atlas XML unreadable (%s)" % type(e).__name__, None
    subs = [e for e in tree.getroot().iter() if _tag(e) == "SubTexture"]
    if not subs:
        return False, "atlas has no frames", None
    im = Image.open(src)
    im.load()
    if getattr(im, "n_frames", 1) > 1:
        return False, "animated PNG", None
    if im.mode not in ("RGBA", "LA", "P"):
        return False, "image has no alpha channel, nothing to trim", None
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    W0, H0 = im.size
    rect_info = {}   # (x,y,w,h) -> (bx, by, tw, th, uid)
    uniq, digest_uid, frames = [], {}, []
    for e in subs:
        if str(e.get("rotated", "false")).lower() == "true":
            return False, "rotated frames are not supported", None
        try:
            x, y, w, h = (_num(e, k) for k in ("x", "y", "width", "height"))
            fx, fy = _num(e, "frameX", 0), _num(e, "frameY", 0)
            fw, fh = _num(e, "frameWidth", w), _num(e, "frameHeight", h)
        except (ValueError, TypeError):
            return False, "non-integer or missing atlas values", None
        if None in (x, y, w, h) or w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > W0 or y + h > H0:
            return False, "a frame lies outside the image", None
        key = (x, y, w, h)
        if key not in rect_info:
            sub = im.crop((x, y, x + w, y + h))
            bb = sub.getchannel("A").getbbox()
            if bb is None:
                tr, bx, by = Image.new("RGBA", (1, 1), (0, 0, 0, 0)), 0, 0
            else:
                tr, bx, by = sub.crop(bb), bb[0], bb[1]
            dg = (tr.size, hashlib.blake2b(tr.tobytes(), digest_size=16).digest())
            if dg not in digest_uid:
                digest_uid[dg] = len(uniq)
                uniq.append((tr, dg))
            rect_info[key] = (bx, by, tr.size[0], tr.size[1], digest_uid[dg])
        frames.append((e, key, fx, fy, fw, fh, "frameX" in e.attrib or "frameWidth" in e.attrib))
    del im
    items = [(i, u[0].size[0], u[0].size[1]) for i, u in enumerate(uniq)]
    widest = max(w for _, w, _ in items)
    best = None
    for k in range(0, 25):
        limit = max(widest, int(widest + (W0 - widest) * k / 24.0)) if W0 > widest else widest
        pos, pw, ph = _pack_shelf(items, pad, limit)
        pw, ph = (pw + 3) // 4 * 4, (ph + 3) // 4 * 4
        cand = (pw * ph, max(pw, ph), limit, pos, pw, ph)
        if best is None or cand[:2] < best[:2]:
            best = cand
    _, _, _, pos, NW, NH = best
    if NW * NH > 0.95 * W0 * H0:
        return False, "already tightly packed", None
    canvas = Image.new("RGBA", (NW, NH), (0, 0, 0, 0))
    for i, (tr, _) in enumerate(uniq):
        canvas.paste(tr, pos[i])
    for e, key, fx, fy, fw, fh, had in frames:
        bx, by, tw, th, uid = rect_info[key]
        px, py = pos[uid]
        e.set("x", str(px)); e.set("y", str(py)); e.set("width", str(tw)); e.set("height", str(th))
        nf = (fx - bx, fy - by, fw, fh)
        if had or nf != (0, 0, tw, th):
            e.set("frameX", str(nf[0])); e.set("frameY", str(nf[1]))
            e.set("frameWidth", str(nf[2])); e.set("frameHeight", str(nf[3]))
    # verify: every packed frame reads back identical, nothing overlaps or leaves the canvas
    for i, (tr, dg) in enumerate(uniq):
        x, y = pos[i]
        if x + tr.size[0] > NW or y + tr.size[1] > NH:
            return False, "internal check failed (bounds)", None
        back = canvas.crop((x, y, x + tr.size[0], y + tr.size[1]))
        if hashlib.blake2b(back.tobytes(), digest_size=16).digest() != dg[1]:
            return False, "internal check failed (pixels)", None
    canvas.save(dst, "PNG", optimize=True)
    import io
    buf = io.BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    return True, "", {"xml": buf.getvalue(), "size": (NW, NH), "frames": len(frames),
                      "unique": len(uniq), "from": (W0, H0)}


def _sha1(path):
    import hashlib
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _duplicates(pngs):
    """Informational only: identical PNG files at different paths. They cannot be merged
    (paths must stay), but each one is a separate texture in memory."""
    by_size = {}
    for rel, p, size in pngs:
        by_size.setdefault(size, []).append((rel, p))
    groups, wasted = [], 0
    for lst in by_size.values():
        if len(lst) < 2:
            continue
        by_hash = {}
        for rel, p in lst:
            by_hash.setdefault(_sha1(p), []).append((rel, p))
        for g in by_hash.values():
            if len(g) > 1:
                try:
                    with Image.open(g[0][1]) as im:
                        wasted += (len(g) - 1) * im.size[0] * im.size[1] * 4
                except Exception:
                    pass
                groups.append([r for r, _ in g])
    return {"groups": len(groups), "decoded_bytes_wasted": wasted, "examples": groups[:5]}


def optimize_mod(input_dir, out_zip, strength="balanced", progress=None):
    progress = progress or _noop
    if strength not in LEVELS:
        raise ValueError("unknown strength: " + str(strength))
    input_dir = os.path.realpath(input_dir)
    if not os.path.isdir(input_dir):
        raise ValueError("input folder does not exist or is not readable")
    out_zip = os.path.abspath(out_zip)
    if os.path.realpath(out_zip).startswith(input_dir + os.sep):
        raise ValueError("output must not be inside the mod folder")
    max_dim = LEVELS[strength]["max_dim"]
    repack_on = LEVELS[strength]["repack"]

    progress("Scanning", 0, 0, "")
    files, empty_dirs, notes = scan(input_dir)
    if not files:
        raise ValueError("the selected folder contains no files")
    abs_of = {rel: p for rel, p, _ in files}
    size_of = {rel: s for rel, _, s in files}
    atlas_map, char_map = _build_maps(files, abs_of)
    pngs = [f for f in files if f[0].lower().endswith(".png")]

    work = tempfile.mkdtemp(prefix="flab_", dir=os.path.dirname(out_zip))
    repl = {}  # rel -> ("file", path) | ("bytes", data)
    details = []
    counts = {"optimized": 0, "resized": 0, "repacked": 0, "skipped": 0, "failed": 0}
    tex_b, tex_a, dims_a, reason_of = {}, {}, {}, {}

    def add(file, action, note="", before=0, after=0):
        if len(details) < MAX_DETAILS:
            details.append({"file": file, "action": action, "note": note, "before": before, "after": after})

    try:
        for i, (rel, p, size) in enumerate(pngs):
            progress("Optimizing images", i, len(pngs), rel)
            tmp = os.path.join(work, "p%d.png" % i)
            rtmp = os.path.join(work, "r%d.png" % i)
            note = ""
            try:
                with Image.open(p) as probe:
                    w, h = probe.size
                w0, h0 = w, h
                tex_b[rel] = tex_a[rel] = w * h * 4
                dims_a[rel] = (w, h)
                if w * h > MAX_PIXELS:
                    counts["skipped"] += 1
                    reason_of[rel] = "too large to process safely on a phone"
                    add(rel, "skipped", "image too large to process safely on a phone (%dx%d)" % (w, h), size, size)
                    continue
                cur, cur_xml, rp_note, rp_info = p, None, "", None
                if repack_on:
                    xmls = atlas_map.get(rel.lower(), [])
                    if len(xmls) == 1:
                        pad = 4 if (max_dim and max(w, h) > max_dim) else 2
                        ok, why, rp_info = _repack(p, abs_of[xmls[0]], rtmp, pad)
                        if ok:
                            cur, cur_xml = rtmp, rp_info["xml"]
                            w, h = rp_info["size"]
                            rp_note = "repacked %dx%d -> %dx%d (%d frames, %d unique)" % (
                                w0, h0, w, h, rp_info["frames"], rp_info["unique"])
                        else:
                            note = "not repacked: " + why
                done = False
                if max_dim and max(w, h) > max_dim:
                    ok, why, plan = _plan_resize(rel, (w, h), max_dim, atlas_map, char_map, files, abs_of, cur_xml)
                    if ok:
                        new_size = _resize_save(cur, tmp, plan["nw"], plan["nh"])
                        repl[rel] = ("file", tmp)
                        repl[plan["xml_rel"]] = ("bytes", plan["xml"])
                        for jr, jb in plan["jsons"].items():
                            repl[jr] = ("bytes", jb)
                        counts["resized"] += 1
                        counts["optimized"] += 1
                        if rp_info:
                            counts["repacked"] += 1
                        tex_a[rel] = plan["nw"] * plan["nh"] * 4
                        dims_a[rel] = (plan["nw"], plan["nh"])
                        reason_of[rel] = "resized"
                        add(rel, "resized", "%s%dx%d -> %dx%d, atlas XML and %d character JSON updated (not tested in-game)"
                            % (rp_note + "; " if rp_note else "", w, h, plan["nw"], plan["nh"], len(plan["jsons"])), size, new_size)
                        done = True
                    else:
                        note = (rp_note + "; " if rp_note else "") + why
                if done:
                    continue
                if rp_info:  # repacked, not resized
                    repl[rel] = ("file", cur)
                    repl[atlas_map[rel.lower()][0]] = ("bytes", cur_xml)
                    counts["optimized"] += 1
                    counts["repacked"] += 1
                    tex_a[rel] = w * h * 4
                    dims_a[rel] = (w, h)
                    reason_of[rel] = (why if max_dim and max(w, h) > max_dim else "within size target") if max_dim else "resize off at this strength"
                    add(rel, "repacked", rp_note + (("; " + why) if max_dim and max(w, h) > max_dim else ""), size, os.path.getsize(cur))
                    continue
                ok, why = _lossless(p, tmp)
                reason_of[rel] = (note or why) if max_dim and max(w, h) > max_dim else (
                    note or ("within size target" if max_dim else "resize off at this strength"))
                if ok:
                    repl[rel] = ("file", tmp)
                    counts["optimized"] += 1
                    add(rel, "optimized", note or "lossless, pixel-identical (no memory change)", size, os.path.getsize(tmp))
                else:
                    counts["skipped"] += 1
                    add(rel, "skipped", (note + "; " if note else "") + why, size, size)
            except (MemoryError, Exception) as e:  # keep original on any failure
                if isinstance(e, Cancelled):
                    raise
                counts["failed"] += 1
                repl.pop(rel, None)
                if rel in tex_b:
                    tex_a[rel] = tex_b[rel]
                reason_of[rel] = "failed, original kept"
                add(rel, "failed", "%s: %s - original kept" % (type(e).__name__, e), size, size)

        dup = _duplicates(pngs)

        part = out_zip + ".part"
        names = []
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            total = len(files)
            for i, (rel, p, size) in enumerate(files):
                if i % 25 == 0:
                    progress("Packaging", i, total, rel)
                ct = zipfile.ZIP_STORED if os.path.splitext(rel)[1].lower() in STORE_EXT else zipfile.ZIP_DEFLATED
                r = repl.get(rel)
                if r is None:
                    zf.write(p, rel, compress_type=ct)
                elif r[0] == "file":
                    zf.write(r[1], rel, compress_type=ct)
                else:
                    zf.writestr(zipfile.ZipInfo(rel, (2020, 1, 1, 0, 0, 0)), r[1], compress_type=ct)
                names.append(rel)
            for d in empty_dirs:
                zf.writestr(d + "/", b"")
                names.append(d + "/")

        progress("Validating", 0, 0, "")
        problems = []
        with zipfile.ZipFile(part) as zf:
            bad = zf.testzip()
            if bad:
                problems.append("corrupt entry: " + bad)
            have = set(zf.namelist())
            for n in names:
                if n not in have:
                    problems.append("missing in output: " + n)
            for rel, p, size in files:
                if rel not in repl and rel in have and zf.getinfo(rel).file_size != size:
                    problems.append("size mismatch: " + rel)
            for rel, r in repl.items():
                data = zf.read(rel) if rel.lower().endswith((".xml", ".json")) else None
                if rel.lower().endswith(".json"):
                    json.loads(data.decode("utf-8"))
                elif rel.lower().endswith(".xml"):
                    ET.fromstring(data)
        valid = not problems
        if valid:
            os.replace(part, out_zip)
        else:
            os.remove(part)
        before = sum(size_of.values())
        after = os.path.getsize(out_zip) if valid else 0
        return {
            "ok": valid, "strength": strength, "validation_ok": valid, "problems": problems[:20],
            "files_total": len(files), "images_total": len(pngs), "optimized": counts["optimized"],
            "resized": counts["resized"], "repacked": counts["repacked"], "skipped": counts["skipped"], "failed": counts["failed"],
            "refs_updated": len(repl) - counts["optimized"], "bytes_before": before, "bytes_after": after,
            "notes": notes[:20], "details": details,
            # decoded texture memory = width*height*4 per image: an upper bound for in-game RAM
            # (only textures actually loaded count). Not a measurement of the game itself.
            "texture_bytes_before": sum(tex_b.values()), "texture_bytes_after": sum(tex_a.values()),
            "top_remaining_textures": [
                {"file": r, "w": dims_a[r][0], "h": dims_a[r][1], "mb": round(tex_a[r] / 1048576.0, 1),
                 "reason": reason_of.get(r, "")}
                for r in sorted(tex_a, key=lambda k: -tex_a[k])[:15] if r in dims_a],
            "duplicate_textures": dup,
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if os.path.exists(out_zip + ".part"):
            try:
                os.remove(out_zip + ".part")
            except OSError:
                pass
