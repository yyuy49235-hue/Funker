# Measured on a real mod: Agoti_Claude_Backup (from your .PsychEngine folder)
43 PNG files, 43.98 MB. Dry-run only (nothing written), on my sandbox CPU. Not run in game.

| Run | PNG size after | Reduction | Notes |
|---|---|---|---|
| Lossless | 41.71 MB | 5.18% | 8 files gained from palette/gray/alpha-drop, the rest only 1-8%. Matches the ~5% you saw in v3/v4. |
| Balanced, scale 0.5, target 45% | 35.74 MB | 18.73% | 4 character atlases resized (BOYFRIEND, bfCar, GF_rock, AGOTI). Target NOT reached. |
| Aggressive, scale 0.5, target 45% | 35.74 MB | 18.73% | Same 4 files; 31 other images refused. Target NOT reached. |

Why 45% is not reachable safely on this mod: the largest remaining files (The_void, Agoti_Cutscene_A/B, Pillar_*, slides, dialogue boxes) are
not character atlases - they are plain images or atlases used by Lua/stage scripts. Their on-screen size depends on script code, so the app
refuses to resize them. Reaching 45% would need a separate, validated script-aware feature (not built) or manual edits.

Time (sandbox CPU): 8192x8192 PNG ~15 s, a 3277x3277 gray+alpha candidate ~35 s; whole mod lossless ~196 s. A phone will be slower: expect minutes.
These runs used the code before the imagePath relaxation; that change can only allow more character atlases (those whose XML imagePath
carries the exporter's name, e.g. "Alt Agoti Sprites_B.png"), not fewer.

## Automatic scale (v5.2) on the same mod - dry-run, sandbox CPU, not run in game
| Level | PNG after | Reduction | Resized images and chosen factor | Target 45% |
|---|---|---|---|---|
| Smart (balanced, auto) | 38.06 MB | 13.46% | Alt_Agoti_Sprites_B x0.60, GF_rock x0.60, AGOTI x0.66; BOYFRIEND refused (detail loss too high at every allowed factor) | not reached |
| Maximum (aggressive, auto) | 34.23 MB | 22.18% | Alt_Agoti_Sprites_B x0.33, BOYFRIEND x0.66, bfCar x0.60, GF_rock x0.25, AGOTI x0.33 | not reached |
Auto is more careful than a fixed 50% (which gave 18.73% in Balanced) because it refuses factors whose sampled detail loss is above the limit.
The limits (2.0 and 5.0 on a 0-255 scale) are starting values chosen by me, NOT validated against how the images look in game. 30 other images are
still refused in Maximum because their scale is controlled by scripts or they have no atlas.
