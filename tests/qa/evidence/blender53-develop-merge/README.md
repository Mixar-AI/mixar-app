<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-2.0-or-later -->

# Develop integration on Blender 5.3

**Latest report:** [develop 4.4.7 integration](../blender53-develop-447/README.md)
records the later `b042cdd60` merge, native splats, Mac/Linux/Windows checks,
and the remaining platform and visual-review limits.

**Later sync:** develop `a57ff48a8` removes the Claude subscription provider
and bumps Mixar to 4.4.6. Its removal is preserved, including deletion of the
provider replay; general BYOK pause/remove coverage remains. The evidence below
records the earlier 4.4.5 run and does not certify the 4.4.6 GUI. The later sync
passed 208 affected BYOK/catalog/relay tests plus translation consistency checks.

PR #2084 merges develop through `c8be570c131d1fb246bb2c3a3673b2c891ec63cd`.
The final product build is `f4147da5786c5c00d4fbee01d51e6cfddb892edc`:
Mixar **4.4.5**, Blender **5.3.0**, upstream
`02f0899d78e374b63e7181d9061e1f7ab03419cc`. Later commits contain QA fixtures
and evidence only. Both macOS Metal and isolated Linux OpenGL builds,
installation and bundled trust/MCP/PDF import checks passed.

## Integration corrections

- Rebased the incoming native Python overlays onto 5.3, preserving the new
  per-user bytecode cache without reverting upstream APIs or autoexec handling.
- Removed the incoming 5.2 Cycles properties overlay. The 5.3 pause interface
  and denoising/upscaling settings remain upstream-owned.
- Rebased three glTF overlays onto 5.3, retaining optional-resource import,
  legacy material-group and exporter logging fixes. Fixed the new required
  image-loader argument for unused-image imports.
- Removed misplaced Claude model validation from the common BYOK delete worker;
  it referenced undefined variables and broke pause/remove for every provider.
- Made Moodboard tooltip ownership use the common UI helper, so introspection
  reports the actual native hover text. Both hosts now pass exact-text checks.
- Restored Windows `-s` on bundled runtime validation; regenerated translation
  catalogs and updated stale provider expectations.

## Running-app verification

All listed passes include state assertions and reviewed screenshots. The
unchanged feature replays ran on `9360a3c19`; final tooltip/UI checks ran on
`419b1b8d7`. The final version/Godot-pin update was rebuilt on both platforms:
startup and identity passed on `f4147da57`, with four UI smoke cases repeated
on Mac. Both new notifier/recovery harness adapters also passed on that
final Mac process. Godot installer tests passed (59); Linux confirmed packaged 0.5.0
constants. Godot itself was not downloaded or launched.

| Replay | Mac | Linux | What it establishes |
| --- | --- | --- | --- |
| `blender53_merged_addons_e2e.py` | Pass | Pass | Eight glTF/GLB import variants, legacy node group, seven export log levels, real Cycles viewport pause and 5.3 settings |
| `byok_claude_code_e2e.py` | Pass | Pass | Native form, signed-out guidance, save/pause/resume/remove with in-memory CLI/HTTP/credential fixtures |
| `context_pdf_attach_e2e.py` | Pass | Pass | Native picker, attachment chips, PDF read/search/render and corrupt/encrypted/image-only cases |
| `context_pdf_paste_e2e.py` | Pass | Not run | Finder-style PDF paste preserves draft; owned clipboard restored |
| `composer_minimise_lifetime_e2e.py` | Pass | Not run | Native composer minimize/reopen, scene-owner deletion and resize |
| `steer_parallel_nudges_e2e.py` | Pass | Not run | Busy/Steer UI, retained draft/reference and new-chat menu with local transport fixtures |
| `layered_mask_single_tile_e2e.py` | Pass | Pass | Actual 1024² cavity/FXAA mask pixels, single tile and original repeating UV preservation |
| `notifier_view_layer_e2e.py` | Pass | Pass | Six scene switches, three window cycles and three file reloads |
| `recovery_read_window_e2e.py` | Pass | Pass | Savepoint, editable recovery, checkpoint and refused unsafe reads |
| `moodboard_media_chrome_e2e.py` | Pass | Pass | Both hosts, four zooms, six tooltips, rename apply/cancel, preview and export cancel |
| `blender53_ui_smoke_e2e.py` | Pass | Pass | UI-01, CHAT-03, CHAT-04, TAB-08: composer, blank-send guard, multiline input and last-scene protection |

The Mac independent reviewer opened 89 images across successful and diagnostic
runs: [review](mac-review.json). Linux's per-case visual verdicts and limits are
in [its review](linux-review.json). Representative unmodified captures:

- [Mac native composer](mac-native-composer.png): actual OS window controls and
  neutral charcoal input; uniform backdrop does not quantify blur.
- [Mac final 4.4.5 composer](mac-latest-composer.png): framebuffer, multiline draft.
- [Mac baked mask](mac-mask.png): exact generated image in the Image Editor.
- [Mac tooltip](mac-moodboard-tooltip.png) and [Linux tooltip](linux-moodboard-tooltip.png).
- [Linux final 4.4.5 desktop](linux-latest-desktop.png): native OpenGL capture.

Replay corrections retain strict assertions: the picker explicitly commits a
live filename edit; notifier setup waits for an already-opening drawer;
steering keeps the pointer over the visible island; Moodboard fixture height
keeps the filename crop clear of the fixed toolbar. Initial failures remain
in the local artifact directory rather than being discarded.

## Standalone tests and limitations

The broad standalone run reported **10,915 passed, 68 failed, 17 errors,
59 skipped**. All 85 unique problem nodes were compared with pre-merge
`449ec6209`: 29 baseline failures, 17 baseline fixture errors, 33 baseline
order-dependent failures, four new stale provider expectations and two new
catalog consistency failures. The six new failures now pass. The diagnostic
selection has identical outcomes before and after the fixes; **the full suite
is not green and was not rerun in full after those fixes**. Per-node categories
are retained in [standalone-triage.json](standalone-triage.json).

Focused native, addon, BYOK, PDF, chat, updater, translation and Godot checks
passed. Windows-only skips remain; updater tests do not prove a real MSI
upgrade. The new release-harness coverage includes KEY-28, IN-15, OUT-16,
RENDER-15, ART-11, TAB-13, UI-21 and BOOT-19; CHAT-23 is reused.

No Windows execution was performed in this pass; the user's separate Windows
test remains authoritative. PRs #2086/#2087 were already included before this
develop merge. Linux Vulkan, real provider authorization, paid generations,
installer execution and the complete free release suite were not validated.
Fixture Stop behavior does not prove backend cancellation. The bounded notifier
smoke does not reproduce every historical intermittent crash. Framebuffer
screenshots do not prove native translucency; this pass is not a performance
certification (cold shader/UI stalls remain in the local stall logs).

Owned Mac QA processes and the Linux sandbox were stopped after testing. Linux
isolation comparison found all 12 other containers unchanged, as well as the
shared Blender 5.2 checkout, upstream and library heads. Build logs, full state
results, diagnostic screenshots and isolation records remain under the ignored
`build/qa/blender53-develop-merge/` directory. No profiles or credentials are
included here.
