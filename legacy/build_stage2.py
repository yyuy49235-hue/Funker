from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
from PIL import Image

HOME = Path.home()
ORIG = HOME / "storage/shared/Agoti"
STAGE1 = HOME / "storage/shared/Agoti_Lite_Output_Stage1"
STAGE2 = HOME / "storage/shared/Agoti_Lite_Output_Stage2"
REPORT = HOME / "FunkerLiteLab/stage2_report.txt"

if not STAGE1.is_dir():
    raise SystemExit("ERROR: Stage 1 folder not found.")
if STAGE2.exists():
    raise SystemExit(
        f"STOP: {STAGE2} already exists. Nothing was changed."
    )

def resolve_image(base, folder, name):
    p = base / folder / name
    if p.is_file():
        return p
    for alt in (name.replace(" ", "_"), name.replace("_", " ")):
        p = base / folder / alt
        if p.is_file():
            return p
    return None

def get_frames(root):
    return [
        n for n in root.iter()
        if all(n.get(k) is not None for k in ("x", "y", "width", "height"))
    ]

# Prepare the list of XML files whose linked image dimensions changed.
jobs = []
for xml_orig in sorted(ORIG.rglob("*.xml")):
    rel = xml_orig.relative_to(ORIG)
    xml_stage1 = STAGE1 / rel
    if not xml_stage1.is_file():
        continue

    root = ET.parse(xml_orig).getroot()
    image_name = root.get("imagePath")
    if not image_name:
        continue

    src_img = resolve_image(ORIG, rel.parent, image_name)
    if src_img is None:
        continue
    out_img = STAGE1 / src_img.relative_to(ORIG)
    if not out_img.is_file():
        continue

    with Image.open(src_img) as im:
        old_size = im.size
    with Image.open(out_img) as im:
        new_size = im.size

    if old_size != new_size:
        jobs.append((rel, old_size, new_size))

# Copy Stage 1 first; only the new Stage 2 copy will be edited.
shutil.copytree(STAGE1, STAGE2)
rows = []
errors = 0

for rel, old_size, new_size in jobs:
    xml_orig = ORIG / rel
    xml_new = STAGE2 / rel
    try:
        original_root = ET.parse(xml_orig).getroot()
        tree = ET.parse(xml_new)
        root = tree.getroot()

        original_frames = get_frames(original_root)
        target_frames = get_frames(root)
        if [n.get("name") for n in original_frames] != [
            n.get("name") for n in target_frames
        ]:
            raise ValueError("Frame names/order differ before editing")

        ow, oh = old_size
        nw, nh = new_size
        sx, sy = nw / ow, nh / oh

        for node in target_frames:
            x, y, w, h = [
                float(node.get(k)) for k in ("x", "y", "width", "height")
            ]
            node.set("x", str(round(x * sx)))
            node.set("y", str(round(y * sy)))
            node.set("width", str(round(w * sx)))
            node.set("height", str(round(h * sy)))

        tree.write(xml_new, encoding="utf-8", xml_declaration=True)

        # Re-read and validate the written XML.
        check_root = ET.parse(xml_new).getroot()
        check_frames = get_frames(check_root)
        if [n.get("name") for n in original_frames] != [
            n.get("name") for n in check_frames
        ]:
            raise ValueError("Frame names/order changed after writing")

        bad = 0
        for node in check_frames:
            x, y, w, h = [
                float(node.get(k)) for k in ("x", "y", "width", "height")
            ]
            if (x < 0 or y < 0 or w <= 0 or h <= 0
                or x + w > nw or y + h > nh):
                bad += 1
        if bad:
            raise ValueError(f"{bad} frame(s) outside resized image bounds")

        rows.append(f"OK | {rel} | {len(check_frames)} frames | bounds valid")

    except Exception as exc:
        errors += 1
        rows.append(f"ERROR | {rel} | {exc}")

summary = [
    f"XML files targeted: {len(jobs)}",
    f"Errors: {errors}",
    "WARNING: This is an intermediate build; not yet tested in-game.",
]
REPORT.write_text("\n".join(rows + [""] + summary) + "\n", encoding="utf-8")

print("Stage 2 copy created:", STAGE2)
print("\n".join(summary))
print("Report:", REPORT)
print("Original and Stage 1 were not modified.")
if errors:
    print("Do not use Stage 2 in-game yet; review the report.")
