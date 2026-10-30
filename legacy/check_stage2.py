from pathlib import Path
import xml.etree.ElementTree as ET
from PIL import Image

MOD = Path.home() / "storage/shared/Agoti_Lite_Output_Stage2"
REPORT = Path.home() / "FunkerLiteLab/stage2_check_report.txt"

rows = []
total = readable = missing = bad_frames = errors = 0

def find_image(folder, name):
    path = folder / name
    if path.is_file():
        return path
    for alt in (name.replace(" ", "_"), name.replace("_", " ")):
        path = folder / alt
        if path.is_file():
            return path
    return None

for xml_path in sorted(MOD.rglob("*.xml")):
    total += 1
    rel = xml_path.relative_to(MOD)

    try:
        root = ET.parse(xml_path).getroot()
        readable += 1
        image_name = root.get("imagePath")

        if not image_name:
            rows.append(f"NO IMAGE PATH | {rel}")
            continue

        image_path = find_image(xml_path.parent, image_name)
        if image_path is None:
            missing += 1
            rows.append(f"MISSING IMAGE | {rel} | {image_name}")
            continue

        with Image.open(image_path) as im:
            iw, ih = im.size

        frames = invalid = 0
        for node in root.iter():
            if not all(node.get(k) is not None for k in
                       ("x", "y", "width", "height")):
                continue
            try:
                x, y, w, h = [
                    float(node.get(k))
                    for k in ("x", "y", "width", "height")
                ]
                frames += 1
                if (x < 0 or y < 0 or w <= 0 or h <= 0
                    or x + w > iw or y + h > ih):
                    invalid += 1
            except (TypeError, ValueError):
                invalid += 1

        bad_frames += invalid
        status = "OK" if invalid == 0 else "CHECK FRAMES"
        rows.append(
            f"{status} | {rel} | image={image_path.name} | "
            f"size={iw}x{ih} | frames={frames} | invalid={invalid}"
        )

    except Exception as exc:
        errors += 1
        rows.append(f"XML ERROR | {rel} | {exc}")

summary = [
    "Funker Lite Lab - Stage 2 Check",
    f"XML files: {total}",
    f"Readable XML files: {readable}",
    f"Missing referenced images: {missing}",
    f"Invalid frame bounds: {bad_frames}",
    f"XML errors: {errors}",
    "",
]

REPORT.write_text("\n".join(summary + rows) + "\n", encoding="utf-8")
print("\n".join(summary))
print("Report:", REPORT)
print("No mod files were changed.")
