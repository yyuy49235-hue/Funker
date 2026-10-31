# What the game logs in your .PsychEngine/logs say (24 files, 5 distinct crashes)
None of them mentions Tabi or any mod name. Facts only; causes are NOT established.
1. x6 (2026-05-14..06-14) Null Object Reference in PsychFlxAnimate.destroy() <- PlayState.destroy(): crash when leaving a song, an animate-atlas object was null.
2. x14 (2026-07-13..10-28, newest two on 10-28) Null Object Reference in TitleState.beatHit() line 537: crash on the title screen. Recurring and recent.
   Not established what is null. Title assets can be replaced by an enabled mod; 17 mods are enabled in modsList.txt.
3. x1 (2026-07-26) Null Object Reference in FlxAnimateFrames.fromSparrow() <- Paths.loadAnimateAtlas <- Tank.prepareCutscene (vanilla Ugh cutscene): an atlas for the cutscene could not load.
4. x1 (2026-09-15) Null Object Reference in FlxDrawQuadsItem.render(): a drawn sprite had no graphic.
5. CopyState logs (2026-05-14, 2026-07-11, identical): 59 base-game files failed to copy on first run (53 .ogg song vocals, 6 .png). Only ~2 images exist
   under assets/shared/images in the folder you sent, so base assets are largely absent from that folder. This may explain items 1/3 but it is a hypothesis.
Engine: stack frames use flxanimate/PsychFlxAnimate, Paths.loadAnimateAtlas and states/stages/Tank -> a recent Psych build (animate-atlas support). The exact version
and the source code are NOT in the folder (no .hx files), so Character.hx is still unavailable.
Check to run (read-only, finds which mods replace the title screen assets):
  find /storage/emulated/0/.PsychEngine/mods -maxdepth 4 \( -iname 'logoBumpin*' -o -iname 'gfDanceTitle*' -o -iname 'titleEnter*' \)
