from pathlib import Path
import xml.etree.ElementTree as ET
from PIL import Image
import math

HOME = Path.home()
ORIG = HOME / "storage/shared/Agoti"
OUT = HOME / "storage/shared/Agoti_Lite_Output_Stage1"
REPORT = HOME / "FunkerLiteLab/validation_report.txt"

def resolve_image(base, folder, name):
    p = base / folder / name
    if p.is_file():
        return p
    for alt_name in (name.replace(" ", "_"), name.replace("_", " ")):
        p = base / folder / alt_name
        if p.is_file():
            return p
    return None

def frames(root):
    return [
        n for n in root.iter()
        if all(n.get(k) is not None for k in ("x", "y", "width", "height"))
    ]

rows = []
counts = {"checked": 0, "resized": 0, "bad_bounds": 0,
          "name_mismatches": 0, "errors": 0}

for xml_orig in sorted(ORIG.rglob("*.xml")):
    rel = xml_orig.relative_to(ORIG)
    xml_out = OUT / rel
    if not xml_out.is_file():
        continue

    try:
        root_orig = ET.parse(xml_orig).getroot()
        root_out = ET.parse(xml_out).getroot()
        image_name = root_orig.get("imagePath")
        if not image_name:
            continue

        img_orig = resolve_image(ORIG, rel.parent, image_name)
        if img_orig is None:
            rows.append(f"NO_SOURCE_IMAGE | {rel} | {image_name}")
            continue

        img_out = OUT / img_orig.relative_to(ORIG)
        if not img_out.is_file():
            rows.append(f"NO_OUTPUT_IMAGE | {rel} | {img_out.name}")
            continue

        with Image.open(img_orig) as im:
            ow, oh = im.size
        with Image.open(img_out) as im:
            nw, nh = im.size

        old_frames, new_frames = frames(root_orig), frames(root_out)
        names_ok = [n.get("name") for n in old_frames] == [
            n.get("name") for n in new_frames
        ]
        resized = (ow, oh) != (nw, nh)
        bad = 0

        if resized:
            sx, sy = nw / ow, nh / oh
            for n in old_frames:
                try:
                    x, y, w, h = [
                        float(n.get(k)) for k in ("x", "y", "width", "height")
                    ]
                    # Simulate scaling and integer rounding used by XML editors.
                    x, y = round(x * sx), round(y * sy)
                    w, h = round(w * sx), round(h * sy)
                    if (x < 0 or y < 0 or w <= 0 or h <= 0
                        or x + w > nw or y + h > nh):
                        bad += 1
                except (TypeError, ValueError):
                    bad += 1

        counts["checked"] += 1
        counts["resized"] += int(resized)
        counts["bad_bounds"] += bad
        counts["name_mismatches"] += int(not names_ok)

        status = "RESIZED" if resized else "UNCHANGED"
        rows.append(
            f"{status} | {rel} | {ow}x{oh}->{nw}x{nh} | "
            f"frames={len(old_frames)} | names_order_ok={names_ok} | "
            f"simulated_bad_bounds={bad}"
        )

    except Exception as e:
        counts["errors"] += 1
        rows.append(f"ERROR | {rel} | {e}")

REPORT.write_text(
    "\n".join(rows) + "\n\nSUMMARY\n" +
    "\n".join(f"{k}={v}" for k, v in counts.items()) + "\n",
    encoding="utf-8"
)
print("Validation finished. No mod files changed.")
print("Report:", REPORT)
print("\n".join(f"{k}: {v}" for k, v in counts.items()))
