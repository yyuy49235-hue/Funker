"""Inspect a mod ZIP without extracting it."""
import stat
import zipfile
from collections import Counter

PSYCH_DIRS = {"characters", "custom_events", "custom_notetypes", "data", "images", "songs",
              "stages", "weeks", "scripts", "music", "sounds", "videos", "fonts", "shaders"}
MAX_FILES = 20000
MAX_UNCOMPRESSED = 4 * 1024 ** 3
MAX_RATIO = 200


def unsafe_name(name):
    n = name.replace("\\", "/")
    return n.startswith("/") or (len(n) > 1 and n[1] == ":") or ".." in n.split("/")


def inspect_zip(path):
    r = {"zip": str(path), "problems": [], "verdict": ""}
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        r["verdict"] = f"REJECTED: cannot open ZIP ({e})"
        return r
    with z:
        infos = z.infolist()
        if len(infos) > MAX_FILES:
            r["problems"].append(f"too many entries ({len(infos)})")
        total = sum(i.file_size for i in infos)
        comp = sum(i.compress_size for i in infos) or 1
        if total > MAX_UNCOMPRESSED:
            r["problems"].append(f"uncompressed size {total} exceeds {MAX_UNCOMPRESSED}")
        if total / comp > MAX_RATIO:
            r["problems"].append(f"compression ratio {total/comp:.0f} looks like a zip bomb")
        for i in infos:
            if unsafe_name(i.filename):
                r["problems"].append(f"unsafe path: {i.filename}")
            if stat.S_ISLNK(i.external_attr >> 16):
                r["problems"].append(f"symbolic link entry: {i.filename}")
        if r["problems"]:
            r["verdict"] = "REJECTED: see problems; nothing was extracted"
            return r
        bad = z.testzip()
        if bad:
            r["verdict"] = f"REJECTED: corrupted entry {bad}"
            return r
        names = [i.filename for i in infos]
        tops = {n.split("/")[0] for n in names if n.split("/")[0]}

        def kids(prefix):
            return {n[len(prefix):].split("/")[0] for n in names if n.startswith(prefix) and n[len(prefix):].split("/")[0]}
        best, score = "", -1
        for pre in [""] + [t + "/" for t in sorted(tops)]:
            s = len(kids(pre) & PSYCH_DIRS)
            if s > score:
                best, score = pre, s
        files = [i for i in infos if not i.filename.endswith("/") and i.filename.startswith(best)]
        ext = Counter(i.filename.rsplit(".", 1)[-1].lower() if "." in i.filename.rsplit("/", 1)[-1] else "(none)" for i in files)
        r.update(mod_root=best or "(top level)", psych_folders=sorted(kids(best) & PSYCH_DIRS),
                 pack_json="pack.json" in kids(best), files=len(files),
                 uncompressed_bytes=sum(i.file_size for i in files), file_types=dict(ext.most_common()))
        r["verdict"] = ("looks like a Psych Engine mod (heuristic only)" if score >= 3
                        else "NOT recognized as a Psych Engine mod")
    return r
