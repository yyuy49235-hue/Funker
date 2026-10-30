from pathlib import Path
from PIL import Image
import io

root = Path('/storage/emulated/0/.PsychEngine/mods/QTMOD_Test_Optimized')
files = list(root.rglob('*.png'))
changed = 0
kept = 0
errors = 0
saved = 0

for p in files:
    try:
        raw = p.read_bytes()
        with Image.open(io.BytesIO(raw)) as im:
            im.load()
            size = im.size
            pixels = im.convert('RGBA').tobytes()
            out = io.BytesIO()
            im.save(out, format='PNG', optimize=True)
        data = out.getvalue()

        if len(data) < len(raw):
            with Image.open(io.BytesIO(data)) as test:
                test.load()
                valid = test.size == size and test.convert('RGBA').tobytes() == pixels
            if valid:
                p.write_bytes(data)
                changed += 1
                saved += len(raw) - len(data)
            else:
                kept += 1
        else:
            kept += 1
    except Exception as e:
        errors += 1
        print('ERROR:', p, e)

print('PNG files:', len(files))
print('Actually optimized:', changed)
print('Left unchanged:', kept)
print('Errors:', errors)
print('Space saved (MB):', round(saved / 1048576, 2))
