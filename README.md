# FunkerLiteLab v0.5 (engine + CLI + Android app source)

Engine: Python 3.10+ and Pillow, in `app/src/main/python/`. Android app: `app/` (Kotlin UI + Chaquopy runs the same engine).
See OPTIMIZATION.md for what the optimizer does. APK: NOT built yet, see BUILD_ON_GITHUB.md. The Kotlin UI has not been compiled or run.

## Commands (run from this folder, e.g. in Termux)
    python3 flab.py mods  "/storage/emulated/0/.PsychEngine/mods" --report ~/flab/mods.json
    python3 flab.py scan  "<mod folder>" --report ~/flab/scan.json
    python3 flab.py atlas "<mod folder>" --report ~/flab/atlas.json
    python3 flab.py inspect "<mod folder>"
    python3 flab.py validate "<original mod>" "<optimized copy>"
    python3 flab.py zipcheck "<mod>.zip"
    python3 flab.py optimize "<mod folder>"                         # dry-run (default)
    python3 flab.py optimize "<mod folder>" --output "<NEW folder>" --apply
    # resizing (off by default): add  --mode balanced|aggressive --allow-resize --target 45   (scale is automatic; --scale 0.5 forces a fixed value)
    python3 run_tests.py

Reports go outside the mod (the tool refuses to write inside it). Manifests go to `workspace` in config.json.

## Safety rules enforced by code (and tests)
- The source mod is never written. `--apply` builds in a hidden staging folder and renames it into place;
  an existing output folder is refused. Cancel/failure removes only the staging folder it created.
- A PNG is replaced only if its decoded RGBA pixels are identical and the new file is strictly smaller (resized files are the only exception, and only when you allowed it).
- Resizing happens only with --allow-resize AND mode balanced/aggressive (UI: tick the box). Details: OPTIMIZATION.md.

## Limits
- Savings are file size only. Lossless PNG does not reduce decoded texture size, and nothing here measures FPS/RAM.
  `est_decoded_bytes` is width x height x bytes-per-pixel, not real game memory.
- Atlas check = rectangles fit the image. Not a compatibility guarantee. JSON/Lua dependency analysis: not done yet.
- Tested on synthetic files plus one real 2048px atlas from your test_run. Not tested on your phone, not in game.
- Peak RAM seen for one synthetic 8192x8192 RGBA image: ~574 MB (in my sandbox). Close other apps on phones with little RAM.

See CAPABILITIES.md (what is missing) and TABI_INVESTIGATION.md (the v4 error).
