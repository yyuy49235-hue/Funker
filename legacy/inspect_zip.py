import sys, zipfile
from collections import Counter

PSYCH_DIRS = {"characters", "custom_events", "custom_notetypes", "data",
              "images", "songs", "stages", "weeks", "scripts", "music",
              "sounds", "videos", "fonts", "shaders"}

def unsafe(name):
    n = name.replace("\\", "/")
    if n.startswith("/") or (len(n) > 1 and n[1] == ":"):
        return True
    return ".." in n.split("/")

if len(sys.argv) != 2:
    raise SystemExit("usage: python inspect_zip.py MOD.zip")

try:
    z = zipfile.ZipFile(sys.argv[1])
except (zipfile.BadZipFile, FileNotFoundError) as e:
    raise SystemExit(f"REJECTED: cannot open ZIP ({e})")

bad = z.testzip()
if bad:
    raise SystemExit(f"REJECTED: corrupted entry: {bad}")

infos = z.infolist()
names = [i.filename for i in infos]
unsafe_names = [n for n in names if unsafe(n)]
if unsafe_names:
    print("REJECTED: unsafe paths found:")
    for n in unsafe_names[:10]:
        print("  ", n)
    raise SystemExit(1)

tops = {n.split("/")[0] for n in names if n.split("/")[0]}
candidates = [""] + [t + "/" for t in sorted(tops)]

def children(root):
    out = set()
    for n in names:
        if n.startswith(root):
            first = n[len(root):].split("/")[0]
            if first:
                out.add(first)
    return out

best_root, best_score = "", -1
for root in candidates:
    score = len(children(root) & PSYCH_DIRS)
    if score > best_score:
        best_root, best_score = root, score

kids = children(best_root)
files = [i for i in infos if not i.filename.endswith("/")
         and i.filename.startswith(best_root)]
ext = Counter(i.filename.rsplit(".", 1)[-1].lower()
              if "." in i.filename.rsplit("/", 1)[-1] else "(none)"
              for i in files)
total = sum(i.file_size for i in files)

print("ZIP integrity: OK")
print("Mod root inside ZIP:", repr(best_root) if best_root else "(top level)")
print("Psych folders found:", sorted(kids & PSYCH_DIRS))
print("pack.json present:", "pack.json" in kids)
print("Files:", len(files), "| Uncompressed size MB:", round(total / 1048576, 2))
print("File types:", dict(ext.most_common()))

if best_score >= 3:
    print("VERDICT: looks like a Psych Engine mod (heuristic, not a guarantee)")
else:
    print("VERDICT: NOT recognized as a Psych Engine mod. Would refuse.")
