# How the optimizer works (v0.5) and what it does NOT do

## Why v0.3 saved only ~5%
v0.3 only re-encoded each PNG with Pillow at the same color type. On already-compressed, anti-aliased art that
gives 0-1% (measured on fixtures: 0.1%). Only images with few colors gain much. Lossless alone cannot reach 45-50%
on typical anti-aliased art; the target needs fewer pixels (resizing).
The percentage itself was computed correctly (100 x (orig - final) / orig from real byte counts).

## Stage A - lossless (always on)
Per PNG the best of these candidates is kept, only if decoded RGBA pixels are identical and the file is strictly smaller:
re-encode (3 DEFLATE settings) | opaque RGBA -> RGB | gray RGB -> L/LA | <=256 exact colors -> palette + tRNS.
gAMA/cHRM/sRGB/iCCP/pHYs are copied byte for byte. Text/tIME/eXIf/bKGD chunks are dropped (listed in the report;
turn off with --keep-metadata). 16-bit, animated and unknown-chunk PNGs are skipped with a reason.
Not available here: oxipng/zopfli/pngquant (not installed, no network). Adding them would give a few % more.

## Stage B - resize (OFF unless you tick "Allow resizing" and pick Balanced/Aggressive)
Runs only if the target is not reached by Stage A, largest files first, and stops as soon as the target is reached.
An image is resized ONLY if all of this is true (otherwise it is skipped and listed as "needs manual fix"):
- a Sparrow XML with the same name exists and points back to it,
- a character JSON under characters/ names it, and no other file (Lua, other JSON, ...) mentions its path,
- it is not pixel-art-like (<=64 colors, hard alpha), long side >= 2048 px (Balanced) or 1024 px (Aggressive),
- the new size keeps the aspect ratio (0.3% tolerance), and it never upscales.
Balanced clamps the scale to >= 50%, Aggressive to >= 25%.
What is edited, and nothing else:
1. PNG pixels (Lanczos, alpha premultiplied by Pillow).
2. Atlas XML: x, y, width, height AND frameX/frameY/frameWidth/frameHeight, scaled by frame EDGES so neighbours stay adjacent.
3. Character JSON: only "scale" = old / factor (inserted if missing). The result is re-parsed to prove nothing else changed.
Why: the game draws a sprite at frame size x scale, so a 4x smaller atlas needs a 4x bigger scale to look the same.
This reasoning follows how Psych Engine loads characters; IT HAS NOT BEEN CHECKED IN GAME. Rounding can still move a frame by 1 px.
Backgrounds and anything created by Lua are NOT resized: their scale lives in script code that a static scan cannot fix safely.
Dynamic Lua (names built at run time) is invisible to the scan, so a "compensable" verdict is a static verdict only.

## Measured on synthetic fixtures (not your mod, not in game)
Lossless only: 0.2% | Balanced 50%: 36.1% (target 45% NOT reached) | Aggressive 25%: 49.3% (reached).
These numbers say nothing about your mod. Run a dry-run on it to get real ones.

## Safety
The source is never written. --apply builds a hidden staging folder, verifies hashes/dimensions, then renames it to the
output path; an existing output folder is refused. Cancel/failure removes only folders this operation created.

## Manual test procedure (what I cannot do for you)
1. Dry-run on the source mod, read the report. 2. Apply to a NEW folder (e.g. VS-Tabi-Revival-main_Lite).
3. Open the original and the Lite copy on the same phone, same song, same graphics settings, restarted between runs.
4. Check: character size and position in idle/sing animations, no missing sprites, no error overlay, stage looks the same.
5. Measure FPS/RAM with the same tool both times (e.g. the game's FPS counter + Android's memory info), at least 3 runs each; compare medians.
6. If a character looks wrong, tell me the file name; the manifest in the workspace lists exactly which files changed.

## v0.5 additions
- Pre-commit validation: the staged copy is compared with the source (paths preserved, untouched files byte-identical, PNGs decode,
  atlases fit, resized atlases scaled consistently AND character scale compensated, references still resolve). Any FAILED check aborts
  the run and nothing is committed. The same check can be run later on any output: `flab.py validate <original> <optimized>`.
- Reference graph (confirmed / inferred / missing / dynamic) and engine hints with confidence: `flab.py inspect <mod>`.
- Resizing is refused when a script alters character scale, for non-Sparrow atlases, and for rotated frames.
- Retry without a problem file: `--exclude <relative path>` (repeatable) leaves that file untouched.
- Failure reports name the stage and the relative file. Export with the app button or read the manifest.
- Static validation is not a game test. Engine test and manual gameplay test are always reported as not done.

## v0.5.2 - automatic scale (no manual percentage)
In the app you now pick only a level: Safe (lossless), Smart (balanced) or Maximum (aggressive). The resize factor is chosen PER IMAGE:
1. ladder of candidate factors, limited by the level (Smart >= 50%, Maximum >= 25%);
2. a factor is rejected if it would change the aspect ratio, if atlas frame edges would land on fractional pixels (mean error above 0.30 px / 0.35 px),
   or if the SAMPLED detail loss is above the level's limit (2.0 / 5.0 on a 0-255 scale);
3. the smallest factor that passes is used; if none passes the image is left alone and the reason is listed.
Detail loss is an estimate from a few content-rich 512 px tiles (shrunk, enlarged back, compared with the original); it is not a proof of how the
image will look in game. The manifest records every factor tried and why it was rejected. Expert override: `--scale 0.5` on the command line.
Choosing Smart/Maximum is the explicit consent to resize; the app asks again before writing the copy.
