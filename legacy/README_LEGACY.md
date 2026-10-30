# legacy/ — your original scripts (kept, not deleted, NOT maintained)

Do not run `engine.py`, `build_stage2.py`, `test_resize.py` or `optimize_pngs.py` on a real mod.
Problems found by reading the code (and testing where marked):

1. **Resizing atlases shrinks sprites in game.** `engine.py` + `build_stage2.py` cut 8192px images to 2048px
   and scale the XML numbers, but the game draws a sprite at (frame size x scale). Frames are now 4x smaller on
   screen unless every character JSON `scale`, stage Lua and offset is also changed. Your reports say this
   was not done ("XML/JSON/Lua references have NOT been adjusted"). 3 images were resized with no XML at all
   (Void_Back, Void_Front, white.png). This is the most likely cause of tiny backgrounds / wrong positions.
   It has NOT been confirmed in game.
2. `build_stage2.py` scales only x, y, width, height. It ignores frameX/frameY/frameWidth/frameHeight
   (trimmed-sprite offsets). The one XML in test_run has none, so it is unknown whether your other atlases do.
   Each number is rounded separately, so frames can move by up to 1px.
3. "bounds valid" (check_stage2, validate_scaled_atlases) only proves rectangles fit inside the image.
   It does not prove the atlas still looks right. The "simulated" check re-does the same arithmetic.
4. `optimize_pngs.py` (TESTED): overwrites files **in place** in QTMOD_Test_Optimized with no backup, no manifest,
   non-atomic `write_bytes` (a crash mid-write can corrupt a PNG). It compares only `.convert('RGBA')`, so a
   16-bit PNG was silently written back as 8-bit and still counted as "valid". It also drops PNG metadata.
5. `engine.py`: if anything fails after `copytree`, a half-built output folder is left behind. `config.json` keys
   `png_optimize` and `preserve_original` were never read. Paths are hard-coded to `storage/shared/Agoti`.
6. Hard-coded Termux paths in most scripts; `resolve_image` copy-pasted 3 times; no tests.

The replacements are in `funkerlitelab/` (see ../README.md). `test_run/` is kept because tests use it as a real sample.
