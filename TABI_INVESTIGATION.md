# Tabi v4 error: what is known and what is needed

Cause: **not established**. No error text, file name or log has been seen. I will not guess.

First tell me where the error appeared:
A) inside the FunkerLiteLab app while optimizing, or B) inside the game (error overlay / crash) when loading the optimized copy.

Send, smallest set first:
1. The exact error text or a screenshot.
2. In the app: tap "Export diagnostic report" and send the text (no file contents, no full paths). Or the newest `manifest-*.json` from
   `Android/data/app.funkerlitelab/files/workspace/`.
3. The relative path of the file named in the error, from the ORIGINAL mod and from the optimized copy (just that file or pair).
4. Which engine + version Tabi runs on (title screen / version text).

You can also run, without me, the new check on your existing v4 output:
  app: fill "mod" with the original and "output" with the optimized copy, tap "Validate optimized copy";
  Termux: python3 flab.py validate "<original Tabi>" "<optimized Tabi>"
It reports exactly which files differ, whether atlases/scales/references are consistent, and says clearly that the game was NOT run.

Defects found by reading v4 (real, fixed, but NOT claimed to be the Tabi cause):
- XML rewritten as UTF-8 even if declared otherwise / BOM dropped (fixed, test added).
- Scripts that change character scale were not detected, so v4 could resize a character whose scale a script also controls (now blocked).
- A failure reported only "Type: message" with no stage or file (now stage + relative file, sanitized traceback).
- No pre-commit validation of the staged output (now added; a failed validation commits nothing).
Still unverified: my scale-compensation formula against the real engine source.
