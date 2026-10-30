from pathlib import Path
from PIL import Image
import shutil
import json

BASE = Path.home()
MOD = BASE / "storage/shared/Agoti"
OUTPUT = BASE / "storage/shared/Agoti_Lite_Output_Stage1"
REPORT = BASE / "FunkerLiteLab/stage1_report.txt"
CONFIG = BASE / "FunkerLiteLab/config.json"

if not MOD.is_dir():
    raise SystemExit(f"ERROR: Mod folder not found: {MOD}")

if OUTPUT.exists():
    raise SystemExit(
        f"STOP: Output already exists:\n{OUTPUT}\n"
        "Nothing was changed. Rename or move that folder before retrying."
    )

config = json.loads(CONFIG.read_text(encoding="utf-8"))
limit = int(config.get("max_dimension", 2048))

print("Funker Lite Lab - Stage 1")
print("Copying mod without changing the original...")
shutil.copytree(MOD, OUTPUT)

changed = []
errors = []
before_total = 0
after_total = 0

for path in sorted(OUTPUT.rglob("*")):
    if not path.is_file():
        continue

    before_total += path.stat().st_size

    if path.suffix.lower() != ".png":
        continue

    try:
        with Image.open(path) as image:
            width, height = image.size

            if max(width, height) <= limit:
                continue

            new_width = max(1, round(width * limit / max(width, height)))
            new_height = max(1, round(height * limit / max(width, height)))
            resized = image.resize(
                (new_width, new_height),
                Image.Resampling.LANCZOS
            )
            resized.save(path, format="PNG", optimize=True)

        new_size = path.stat().st_size
        old_size = Image.open(MOD / path.relative_to(OUTPUT)).size
        changed.append(
            f"{path.relative_to(OUTPUT)} | "
            f"{width}x{height} -> {new_width}x{new_height} | "
            f"{new_size / 1024 / 1024:.2f} MB"
        )
        print(f"Resized: {path.relative_to(OUTPUT)}")

    except Exception as exc:
        errors.append(f"{path.relative_to(OUTPUT)} | {exc}")

after_total = sum(p.stat().st_size for p in OUTPUT.rglob("*") if p.is_file())

report = [
    "Funker Lite Lab - Stage 1 Report",
    f"Original folder: {MOD}",
    f"Output folder: {OUTPUT}",
    f"Maximum image dimension: {limit}",
    f"Images resized: {len(changed)}",
    f"Errors: {len(errors)}",
    f"Output size: {after_total / 1024 / 1024:.2f} MB",
    "",
    "RESIZED IMAGES:",
    *changed,
    "",
    "ERRORS:",
    *(errors or ["None"]),
    "",
    "IMPORTANT: XML/JSON/Lua references have NOT been adjusted.",
    "This output is an intermediate test and is NOT game-ready yet.",
    "Original mod files were not modified."
]
REPORT.write_text("\n".join(report) + "\n", encoding="utf-8")

print("\nFinished.")
print("Images resized:", len(changed))
print("Errors:", len(errors))
print(f"Output size: {after_total / 1024 / 1024:.2f} MB")
print("Report:", REPORT)
print("Original mod untouched.")
print("WARNING: Stage 1 output is NOT game-ready yet.")
