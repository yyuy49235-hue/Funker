"""Compare decoded-texture memory (width*height*4 per PNG) of two mods (folder or ZIP).

    python measure.py ORIGINAL_MOD_FOLDER OPTIMIZED_MOD_FOLDER_OR_ZIP

This is what the textures occupy once decoded. It is NOT in-game RAM: only textures the
game actually loads count, and the game engine adds its own overhead.
"""
import os
import struct
import sys
import zipfile


def _png_size(f):
    head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])


def textures(path):
    out, total = {}, 0
    if os.path.isdir(path):
        for dp, _, fn in os.walk(path):
            for f in fn:
                p = os.path.join(dp, f)
                total += os.path.getsize(p)
                if f.lower().endswith(".png"):
                    with open(p, "rb") as fh:
                        s = _png_size(fh)
                    if s:
                        out[os.path.relpath(p, path).replace(os.sep, "/")] = s
    else:
        with zipfile.ZipFile(path) as z:
            for i in z.infolist():
                total += i.file_size
                if i.filename.lower().endswith(".png"):
                    with z.open(i) as fh:
                        s = _png_size(fh)
                    if s:
                        out[i.filename] = s
    return out, total


def main(a, b):
    ta, fa = textures(a)
    tb, fb = textures(b)
    ra = sum(w * h * 4 for w, h in ta.values())
    rb = sum(w * h * 4 for w, h in tb.values())
    mb = lambda v: "%.1f MB" % (v / 1048576.0)
    print("files on disk (uncompressed): %s -> %s" % (mb(fa), mb(fb)))
    print("decoded textures: %s -> %s (%.1f%% less)" % (mb(ra), mb(rb), 100.0 * (ra - rb) / ra if ra else 0))
    print("\nLargest textures still present:")
    for k, (w, h) in sorted(tb.items(), key=lambda kv: -kv[1][0] * kv[1][1])[:15]:
        print("  %6.1f MB  %5dx%-5d %s" % (w * h * 4 / 1048576.0, w, h, k))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
