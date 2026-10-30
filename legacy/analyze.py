from pathlib import Path
from PIL import Image

MOD = Path.home() / "storage/shared/Agoti"
MAX_DIMENSION = 2048

print("Funker Lite Lab - Safe Image Analysis")
print("-" * 42)

candidates = 0
potential_bytes = 0

for path in sorted(MOD.rglob("*")):
    if not path.is_file() or path.suffix.lower() != ".png":
        continue

    try:
        with Image.open(path) as img:
            width, height = img.size

        if max(width, height) > MAX_DIMENSION:
            size = path.stat().st_size
            candidates += 1
            potential_bytes += size

            print(
                f"{path.relative_to(MOD)} | "
                f"{width}x{height} | {size / 1024:.1f} KB"
            )

    except Exception as error:
        print("Could not inspect:", path.name, error)

print("-" * 42)
print("Large PNG candidates:", candidates)
print(f"Their current total size: {potential_bytes / (1024 * 1024):.2f} MB")
print("Analysis only: no files modified.")
