from pathlib import Path
from collections import Counter

MODS = Path("/storage/emulated/0/.PsychEngine/mods")
PSYCH_DIRS = {
    "characters", "custom_events", "custom_notetypes", "data",
    "images", "songs", "stages", "weeks", "scripts", "music",
    "sounds", "videos", "fonts", "shaders"
}

def inspect_mod(root):
    entries = list(root.rglob("*"))
    files = [p for p in entries if p.is_file()]
    dirs = {p.name for p in entries if p.is_dir()}
    top_dirs = {p.name for p in root.iterdir() if p.is_dir()}
    top_files = {p.name for p in root.iterdir() if p.is_file()}

    types = Counter(
        p.suffix[1:].lower() if p.suffix else "(none)"
        for p in files
    )
    total_size = sum(p.stat().st_size for p in files)
    found = sorted(top_dirs & PSYCH_DIRS)
    score = len(found)

    print(f"\n========== {root.name} ==========")
    print(f"Mod root: {root.name}/")
    print("Psych folders found:", found)
    print("pack.json present:", "pack.json" in top_files)
    print(f"Files: {len(files)} | Size: {total_size / 1048576:.2f} MB")
    print("File types:", dict(types.most_common()))

    if score >= 3:
        print("VERDICT: looks like a Psych Engine mod (heuristic, not a guarantee)")
    else:
        print("VERDICT: NOT recognized as a Psych Engine mod")

def main():
    if not MODS.is_dir():
        raise SystemExit(f"Mods directory not found: {MODS}")

    mods = sorted(
        (p for p in MODS.iterdir() if p.is_dir()),
        key=lambda p: p.name.lower()
    )

    print("Funker Lite Lab - Installed Mods Inspector")
    print("Mods directory:", MODS)
    print("Mod folders:", len(mods))

    for mod in mods:
        try:
            inspect_mod(mod)
        except Exception as exc:
            print(f"\n========== {mod.name} ==========")
            print("SCAN ERROR:", exc)

    archives = sorted(
        p for p in MODS.iterdir()
        if p.is_file() and p.suffix.lower() == ".zip"
    )
    for archive in archives:
        print(f"\n========== ZIP: {archive.name} ==========")
        print("Use inspect_zip.py to inspect this archive.")

if __name__ == "__main__":
    main()
