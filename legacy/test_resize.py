from pathlib import Path
from PIL import Image
import xml.etree.ElementTree as ET
import shutil

source = Path.home() / "storage/shared/Agoti"
test = Path.home() / "FunkerLiteLab/test_run"

relative = Path("images/agoti/images/Agoti_Cutscene_A.png")
png_src = source / relative
xml_src = png_src.with_suffix(".xml")

png_out = test / relative
xml_out = png_out.with_suffix(".xml")

if not png_src.is_file() or not xml_src.is_file():
    raise SystemExit("ERROR: PNG or XML file not found.")

with Image.open(png_src) as img:
    old_w, old_h = img.size
    scale = min(1.0, 2048 / max(old_w, old_h))
    new_size = (round(old_w * scale), round(old_h * scale))
    resized = img.resize(new_size, Image.Resampling.LANCZOS)

png_out.parent.mkdir(parents=True, exist_ok=True)
resized.save(png_out, optimize=True)

tree = ET.parse(xml_src)
root = tree.getroot()

for node in root.iter():
    for attr in ("x", "y", "width", "height"):
        value = node.get(attr)
        if value is not None:
            try:
                node.set(attr, str(round(float(value) * scale)))
            except ValueError:
                pass

xml_out.parent.mkdir(parents=True, exist_ok=True)
tree.write(xml_out, encoding="utf-8", xml_declaration=True)

print("Test resize completed.")
print(f"Image: {old_w}x{old_h} -> {new_size[0]}x{new_size[1]}")
print(f"Scale factor: {scale:.6f}")
print("PNG output:", png_out)
print("XML output:", xml_out)
print("Original files were not changed.")
