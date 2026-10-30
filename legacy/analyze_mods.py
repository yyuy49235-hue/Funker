from pathlib import Path
from collections import Counter
from PIL import Image

MODS = Path("/storage/emulated/0/.PsychEngine/mods")
REPORT = Path.home() / "FunkerLiteLab" / "optimization_report.txt"
IMAGE_LIMIT = 2048
TOP_FILES = 10

def analyze_mod(root):
    files = [p for p in root.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    types = Counter()
    image_bytes = audio_bytes = video_bytes = 0
    large_images = []
    unreadable_images = []

    for path in files:
        size = path.stat().st_size
        ext = path.suffix.lower()
        types[ext or "(no extension)"] += 1

        if ext in {".png", ".jpg", ".jpeg", ".webp"}:
            image_bytes += size
            try:
                with Image.open(path) as img:
                    w, h = img.size
                    if max(w, h) > IMAGE_LIMIT:
                        large_images.append(
                            (size, path.relative_to(root), w, h)
                        )
            except Exception as exc:
                unreadable_images.append(
                    f"{path.relative_to(root)}: {exc}"
                )

        elif ext in {".ogg", ".mp3", ".wav", ".flac", ".opus"}:
            audio_bytes += size
        elif ext in {".mp4", ".webm", ".avi", ".mov"}:
            video_bytes += size

    largest = sorted(
        ((p.stat().st_size, p.relative_to(root))
         for p in files),
        reverse=True
    )[:TOP_FILES]

    lines = [
        f"========== {root.name} ==========",
        f"Files: {len(files)}",
        f"Total size: {total / 1048576:.2f} MB",
        f"Images: {image_bytes / 1048576:.2f} MB",
        f"Audio: {audio_bytes / 1048576:.2f} MB",
        f"Video: {video_bytes / 1048576:.2f} MB",
        f"File types: {dict(types.most_common())}",
        "",
        f"LARGEST {TOP_FILES} FILES:"
    ]

    lines.extend(
        f"{size / 1048576:.2f} MB | {name}"
        for size, name in largest
    )

    lines += ["", f"IMAGES OVER {IMAGE_LIMIT}px:"]
    lines.extend(
        f"{w}x{h} | {size / 1048576:.2f} MB | {name}"
        for size, name, w, h in
        sorted(large_images, reverse=True)
    )
    if not large_images:
        lines.append("None")

    lines += ["", "UNREADABLE IMAGES:"]
    lines.extend(unreadable_images or ["None"])
    lines += [
        "",
        "NOTE: Analysis only. No files were modified.",
        "Large dimensions do not automatically mean an image is safe to resize."
    ]
    return "\n".join(lines)

def main():
    if not MODS.is_dir():
        raise SystemExit(f"Mods directory not found: {MODS}")

    reports = []
    mods = sorted(
        (p for p in MODS.iterdir() if p.is_dir()),
        key=lambda p: p.name.lower()
    )

    print("Funker Lite Lab - Optimization Analysis")
    print("Mods found:", len(mods))

    for mod in mods:
        print("Analyzing:", mod.name)
        try:
            reports.append(analyze_mod(mod))
        except Exception as exc:
            reports.append(
                f"========== {mod.name} ==========\nSCAN ERROR: {exc}"
            )

    REPORT.write_text(
        "\n\n".join(reports) + "\n",
        encoding="utf-8"
    )
    print("Analysis complete. No mod files were changed.")
    print("Report:", REPORT)

if __name__ == "__main__":
    main()
