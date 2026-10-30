from pathlib import Path
import xml.etree.ElementTree as ET
from PIL import Image

MOD = Path.home() / "storage/shared/Agoti"
REPORT = Path.home() / "FunkerLiteLab/xml_report.txt"

rows = []
total = 0
readable = 0
missing_images = 0
bad_frames = 0

for xml_path in sorted(MOD.rglob("*.xml")):
    total += 1

    try:
        root = ET.parse(xml_path).getroot()
        readable += 1

        image_name = root.get("imagePath")
        if not image_name:
            rows.append(f"NO IMAGE PATH | {xml_path.relative_to(MOD)}")
            continue

        image_path = xml_path.parent / image_name

        if not image_path.is_file():
            missing_images += 1
            rows.append(
                f"MISSING IMAGE | {xml_path.relative_to(MOD)} | {image_name}"
            )
            continue

        with Image.open(image_path) as image:
            image_width, image_height = image.size

        frames = 0
        invalid = 0

        for node in root.iter():
            if not all(node.get(k) is not None for k in
                       ("x", "y", "width", "height")):
                continue

            try:
                x, y, w, h = (
                    float(node.get(k))
                    for k in ("x", "y", "width", "height")
                )
                frames += 1

                if (x < 0 or y < 0 or w <= 0 or h <= 0
                        or x + w > image_width
                        or y + h > image_height):
                    invalid += 1
            except ValueError:
                invalid += 1

        bad_frames += invalid
        status = "OK" if invalid == 0 else "CHECK FRAMES"
        rows.append(
            f"{status} | {xml_path.relative_to(MOD)} | "
            f"image={image_name} | size={image_width}x{image_height} | "
            f"frames={frames} | invalid={invalid}"
        )

    except Exception as exc:
        rows.append(f"XML ERROR | {xml_path.relative_to(MOD)} | {exc}")

header = [
    "Funker Lite Lab - XML and Image Check",
    f"XML files: {total}",
    f"Readable XML files: {readable}",
    f"Missing referenced images: {missing_images}",
    f"Invalid frame bounds: {bad_frames}",
    "Check results below:",
    ""
]

REPORT.write_text("\n".join(header + rows) + "\n", encoding="utf-8")
print("\n".join(header))
print("Report saved to:", REPORT)
print("Original mod files were not modified.")
