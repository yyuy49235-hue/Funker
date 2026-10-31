# Capabilities and missing inputs (v0.5) — updated each stage

| Item | State |
|---|---|
| Source of this project (v4 repo) | Available (my copy of the code, not your GitHub repo) |
| Tabi error text / screenshot | **Requested from you** |
| `manifest-*.json` / diagnostic report of the failing run | **Requested from you** |
| Original Tabi file named in the error + the optimized version of it | **Requested from you** |
| Engine name + version your Tabi build runs on | **Requested from you** |
| `Character.hx` of that exact engine version | **Requested from you** (public download blocked for me: github.com refuses automated access) |
| Official Psych docs/source via the web | Not technically accessible (github.com robots block); third-party docs reached, not authoritative |
| Running the real game/engine in this environment | Not technically accessible (Haxe/OpenFL game, no runtime or Android device here) |
| Android APK build here | Not technically accessible (no JDK/SDK/network for Gradle) - GitHub Actions builds it |
| Android emulator / instrumentation tests | Not technically accessible here |
| Direct push to your GitHub repo | Not available (no GitHub connector found in the directory, bash has no network) |
| Psych Engine as a compatibility reference mod | Unnecessary for now |

## Validation states this version can really produce
Analysis, optimization, structural validation, static compatibility checks. Never produced here: real engine test, manual gameplay test.

## Adapters
sparrow-xml (modifiable) | packer-txt, json-atlas, animate-atlas (recognized, never modified).
