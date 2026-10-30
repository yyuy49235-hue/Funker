"""Read-only recursive scanner. Symlinks are recorded, never followed."""
import json
import os
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path

CATEGORIES = {
    "image": {".png", ".jpg", ".jpeg", ".webp", ".gif"},
    "metadata": {".xml", ".json", ".lua", ".txt", ".ini", ".cfg", ".yaml", ".yml", ".hx", ".frag", ".vert"},
    "audio": {".ogg", ".wav", ".mp3"},
    "archive": {".zip", ".rar", ".7z"},
}
MAX_PARSE_BYTES = 20 * 1024 * 1024


@dataclass
class FileRecord:
    rel_path: str
    ext: str
    category: str
    size: int
    mtime: float
    readable: bool
    parse_status: str  # "ok" | "failed" | "not_applicable" | "skipped_large"
    parse_error: str = ""
    is_symlink: bool = False


def classify(ext):
    for cat, exts in CATEGORIES.items():
        if ext in exts:
            return cat
    return "unknown"


def _parse_check(path, ext, size):
    if ext not in (".json", ".xml"):
        return "not_applicable", ""
    if size > MAX_PARSE_BYTES:
        return "skipped_large", f"larger than {MAX_PARSE_BYTES} bytes"
    try:
        if ext == ".json":
            with open(path, "r", encoding="utf-8-sig") as f:
                json.load(f)
        else:
            ET.parse(path)  # ElementTree does not fetch external entities
        return "ok", ""
    except Exception as e:  # recorded, never hidden
        return "failed", f"{type(e).__name__}: {e}"


def scan(root, cancel=None):
    """Yield FileRecord for every file under root (including unknown types)."""
    root = Path(root)
    stack = [root]
    while stack:
        if cancel is not None and cancel.is_set():
            return
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError as e:
            yield FileRecord(str(d.relative_to(root)) + "/", "", "unreadable_dir", 0, 0.0,
                             False, "failed", f"{type(e).__name__}: {e}")
            continue
        for e in sorted(entries, key=lambda x: x.name):
            rel = str(Path(e.path).relative_to(root))
            if e.is_symlink():
                yield FileRecord(rel, "", "symlink", 0, 0.0, False, "not_applicable", "not followed", True)
            elif e.is_dir(follow_symlinks=False):
                stack.append(Path(e.path))
            elif e.is_file(follow_symlinks=False):
                ext = os.path.splitext(e.name)[1].lower()
                try:
                    st = e.stat(follow_symlinks=False)
                    readable = os.access(e.path, os.R_OK)
                except OSError as ex:
                    yield FileRecord(rel, ext, classify(ext), 0, 0.0, False, "failed", str(ex))
                    continue
                ps, pe = _parse_check(e.path, ext, st.st_size) if readable else ("failed", "unreadable")
                yield FileRecord(rel, ext, classify(ext), st.st_size, st.st_mtime, readable, ps, pe)


def summarize(records):
    records = list(records)
    by_ext, by_cat = Counter(), Counter()
    for r in records:
        by_ext[r.ext or "(none)"] += r.size
        by_cat[r.category] += r.size
    return {
        "file_count": len(records),
        "total_bytes": sum(r.size for r in records),
        "bytes_by_extension": dict(by_ext.most_common()),
        "bytes_by_category": dict(by_cat.most_common()),
        "largest_files": [asdict(r) for r in sorted(records, key=lambda r: -r.size)[:20]],
        "unreadable": sum(1 for r in records if not r.readable),
        "parse_failures": [r.rel_path for r in records if r.parse_status == "failed"],
        "unknown_type_files": sum(1 for r in records if r.category == "unknown"),
    }
