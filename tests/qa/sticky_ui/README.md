<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-2.0-or-later -->

# Sticky-UI live suite (macOS and Windows)

Runs every live check of the sticky-UI work against the built app through the
QA harness. One fresh, isolated QA app per case. No credits are spent: a fake
busy state stands in for an agent turn.

## Run

```bash
# macOS
python3 tests/qa/sticky_ui/run_suite.py

# Windows (PowerShell or cmd)
set QA_HARNESS=C:\src\mixar-qa-harness
python tests\qa\sticky_ui\run_suite.py --build build\Dev\bin

# one case
python3 tests/qa/sticky_ui/run_suite.py --cases mode_switch_keeps_island
```

Needs: a Dev build (dev-bypass login in its `mixar.json`), a checkout of
`mixar-qa-harness` (`QA_HARNESS`, default `~/mixar-src/mixar-qa-harness`),
Python 3.10+. macOS also needs `swiftc` (Xcode command line tools) for the
window-stack reader. Windows needs nothing extra.

**Do not touch the machine while it runs.** Window-stack checks need the app
on screen: switching desktops, locking the screen or covering the app makes
those steps fail with an "environment" message. The suite keeps the display
awake itself.

## Results

`<harness>/out/sticky-ui-<time>/summary.txt` (and `summary.json`), one line per case:

| Status | Meaning |
| --- | --- |
| PASS | ran and every assertion held |
| FAIL | the reason is on the line; `traceback.txt` and the app log are in the case folder |
| N/A | cannot run on this platform; the reason is on the line |
| PIN | covered by a unit test only (`python -m pytest tests/...`) |

Exit code 1 if any case failed.

## Cases

| Case | Change | Checks | Platform notes |
| --- | --- | --- | --- |
| `checkpoint_send_keeps_island` | 3.1 | turn checkpoint < 3 s, chat windows not closed | all |
| `metal_pool_sweep` | 3.2 | unit pin | N/A on Windows (no Metal) |
| `turn_no_viewport_redraws` | 3.3, 3.5 | ≤ 6 viewport redraws in 3 s of a turn; native halo active | all |
| `toast_click_gate` | 3.4 | unit pin | all |
| `engine_switch_prewarm` | 3.6 | shaders warmed at idle; first Engine switch < 1.5 s freeze | all |
| `render_responsive` | 3.7 | main loop keeps ≥ 40% of its idle rate during a Cycles render, no gap ≥ 1 s | macOS Dock fix; measures the Windows taskbar path too |
| `history_undo_one_folder` | 3.8 | undo/redo keeps one history folder per scene | Ctrl+Z on Windows |
| `preview_private_scene` | 3.9 | agent inspection/final renders leave the user's scene and Rendered viewport untouched; copy never a tab, removed after; undo mid-render clean | all |
| `mode_switch_keeps_island` | 3.10 | Engine click keeps the chat open and on top; viewport click collapses it, visibly | macOS checks the fade plays in front; Windows collapse is instant |
| `stall_log_attribution` | 4.1, 4.2 | five induced stalls logged with the right cause and Python stack | all (`QA_MIXED` launch) |
| `preview_render_memory` | 3.11 | Blender's allocator grows < 5 MiB per 1600×1200 agent inspection (old build: +39 to +59) | all |
| `checkpoint_restore_no_orphan_layouts` | 3.12 | a snapshot taken with the island open, loaded twice, leaves no orphan chat screens or layouts | all |
| `halo_breathes` | 3.15 | the main window repaints about 20 times a second during a turn with no input (old build: 0), and once more to clear the halo | all (`QA_MIXED` launch, stall log at every pass) |
| `toast_survives_file_load` | 3.13 | a sticky toast keeps its timer, flag and working close button after a load | all |

## Calibration

`preview_private_scene` fails a viewport whose mean RGB is ≤ 0.15, halfway
between the two measured cases on macOS: the black "Loading render kernels"
viewport 0.073, the normal EEVEE view of the test scene 0.237–0.247. Recheck on
Windows with the first run's `0_before.png` (the value is in `summary.json`).
