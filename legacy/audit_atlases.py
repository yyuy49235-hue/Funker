from pathlib import Path
import xml.etree.ElementTree as ET
from PIL import Image

HOME = Path.home()
ORIG = HOME / "storage/shared/Agoti"
OUT = HOME / "storage/shared/Agoti_Lite_Output_Stage1"
REPORT = HOME / "FunkerLiteLab/atlas_audit.txt"

rows = []
for xml_out in sorted(OUT.rglob("*.xml")):
    rel = xml_out.relative_to(OUT)
    xml_orig = ORIG / rel

    try:
        root_out = ET.parse(xml_out).getroot()
        root_orig = ET.parse(xml_orig).getroot()
        image_name = root_orig.get("imagePath")

        if not image_name:
            rows.append(f"NO IMAGE PATH | {rel}")
            continue

        img_orig = ORIG / rel.parent / image_name
        img_out = OUT / rel.parent / image_name

        # Account for known filename mismatches without changing files.
        if not img_orig.is_file():
            alternatives = [
                img_orig.with_name(img_orig.name.replace(" ", "_")),
                img_orig.with_name(img_orig.name.replace("_", " "))
            ]
            img_orig = next((p for p in alternatives if p.is_file()), img_orig)
            img_out = OUT / img_orig.relative_to(ORIG)

        if not img_orig.is_file() or not img_out.is_file():
            rows.append(f"MISSING IMAGE | {rel} | {image_name}")
            continue

        with Image.open(img_orig) as im:
            old_w, old_h = im.size
        with Image.open(img_out) as im:
            new_w, new_h = im.size

        def get_frames(root):
            return [
                n for n in root.iter()
                if all(n.get(k) is not None for k in ("x", "y", "width", "height"))
            ]

        old_frames = get_frames(root_orig)
        new_frames = get_frames(root_out)
        resized = (old_w, old_h) != (new_w, new_h)
        names_ok = [n.get("name") for n in old_frames] == [
            n.get("name") for n in new_frames
        ]

        scale_x = new_w / old_w
        scale_y = new_h / old_h
        bad = 0
        if resized:
            for n in old_frames:
                x, y, w, h = [float(n.get(k)) for k in ("x", "y", "width", "height")]
                if (x < 0 or y < 0 or w <= 0 or h <= 0
                    or x + w > old_w or y + h > old_h):
                    bad += 1

        status = "RESIZED" if resized else "UNCHANGED"
        rows.append(
            f"{status} | {rel} | image={image_name} | "
            f"{old_w}x{old_h}->{new_w}x{new_h} | "
            f"frames={len(old_frames)} | names_match={names_ok} | "
            f"source_frames_outside_original={bad}"
        )

    except Exception as e:
        rows.append(f"ERROR | {rel} | {e}")

REPORT.write_text("\n".join(rows) + "\n", encoding="utf-8")
print("Atlas audit complete.")
print("XML files checked:", len(rows))
print("Report:", REPORT)
print("No mod files were changed.")
