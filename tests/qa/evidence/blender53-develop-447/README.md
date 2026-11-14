<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-2.0-or-later -->

# Develop 4.4.7 integration on Blender 5.3

The focused state checks passed on macOS, Linux and Windows. The selected
screenshots below were opened and inspected. **Windows visual review remains
partial:** 31 earlier startup/auth images are reviewed; remaining screenshots
await transfer approval. This report does not certify an entirely green suite
or every GPU configuration.

PR #2084 includes develop through `b042cdd608c5d51d09de923a3faebbb3ffc4c10d`.
The initial merge was `bb20839b7677bf9456d64377413bd85e63176aa6`; the first combined native-splat build
was `d91c21528b781785eb89248d9362fb64074e79b8`, the retired KIRI install
fix at `34a6797f4bf392ec173caf1128ba4336e431c30e`, and the preview CPU fix at
`1a9e791e3b199af1016917a3e2fe37c7272b0212`. Final runtimes are Mixar **4.4.7**,
Blender **5.3.0**, upstream `02f0899d78e374b63e7181d9061e1f7ab03419cc`.

Final Mac and Windows runs used UAT8: backend branch `chore/blender-5-3-upgrade`,
commit `6f10c1d16`, version **3.3.11**, including native-splat routing PR #2039.
Earlier Mac auth/UI runs used UAT8 develop at `36ddc74ff` (3.3.9).
Linux used its own isolated sandbox backend. All runs used disposable QA
profiles and synthetic credential/transport fixtures, with no paid provider
requests or real account-store mutations.

## Running-app coverage

| Platform | Runtime and coverage | State and vision |
| --- | --- | --- |
| Linux / NVIDIA L4 / OpenGL | Auth/Codex at `bb20839b7`; startup, hidden-window/pill, four UI smoke cases and native splats at `34a6797f4`; default + CPU preview replay at `1a9e791e3` | Passed; reviewed 84 earlier images, all 34 broad-run images and 21 follow-up images |
| macOS / Apple M4 | Auth/Codex and six headless splat checks on preceding snapshots; normal final `1a9e791e3` build repeated startup, native-splat CPU GUI, hidden/pill and four UI smoke cases | Passed; earlier independent review covered 82 source images; final representatives below reviewed |
| Windows Server 2022 / Tesla T4 | Eleven OpenGL cases at `34a6797f4`; at `1a9e791e3`, two splat GUI cases, six headless checks and six actual Vulkan UI/glass cases | All 19 GUI case runs and six headless checks passed state assertions; only 31 startup/AUTH-08/10/12 images reviewed so far |

The focused auth cases cover refresh failure/recovery, interrupted login,
secret exposure and account races. KEY-22 exercises 15 Codex reference/fault/race groups on Mac and 13
applicable groups on Linux/Windows; permission gaps are retained below. Hidden-window
testing checks the pill target and restore, settled observation and stale
geometry refusal. Linux deliberately draws its collapsed windows, so a
hidden-window capture-refusal assertion is not applicable there.

The six background splat cases cover SPZ orientation, raw PLY import, invalid
PLY refusal, EEVEE/Cycles/Workbench rendering and hide-render behavior, collider
cleanup, and legacy conversion/idempotence. The GUI replay uses real menus and
file pickers, hide/unhide, selection, delete/undo, saved legacy-file migration,
and the production local `engine=splat` preview. Fixtures contain 400 points;
they do not represent large production worlds.

Replayable client scenarios: [hidden windows](../../blender53_hidden_windows_e2e.py),
[UI smoke](../../blender53_ui_smoke_e2e.py),
[native splat GUI](../../native_splats_gui_e2e.py), and
[native splat background](../../native_splats_background.py).

## Corrections proven during this run

The incremental install retained the retired KIRI add-on even after its source
was removed. This reproduced before the fix; normal `make build` at
`34a6797f4` removed it without manual deletion. Four install-layout regression
tests failed before the fix; the corrected selection passed 19 with 10 platform
skips. Unrelated and user-installed add-ons remain outside the cleanup scope.

The preview's CPU request inherited `cycles.device=GPU` from the copied scene.
Four regression tests and a live actual-device assertion failed before the
fix. The intermediate Mac Python-patched snapshot reported CPU in 1.701 s;
the normal committed `1a9e791e3` build then passed the full replay with actual
CPU in **1.536 s**. Linux reported GPU in **1.685 s** for the default path and
CPU in **0.664 s** when requested. Windows reported CPU in **4.104 s** by
default and **5.336 s** explicitly. Each preview was 320×240 at eight samples,
preserved source state, restored AUTO, and used no automatic fallback.

## Reviewed representatives

These are original, unmodified PNGs. [screenshots.json](screenshots.json) records
their exact revision, size, SHA-256 and visual scope.

| Image | What it establishes |
| --- | --- |
| [Linux native composer](linux-composer-native.png) | Dark composer, readable controls and scene layout at `34a6797f4`; no controlled blur/translucency claim |
| [Linux native PLY](linux-native-ply.png) | Fully shaded imported splats and selection outline at `1a9e791e3` |
| [Linux CPU preview](linux-preview-cpu.png) | Visible cloud paired with actual CPU metadata at `1a9e791e3` |
| [Linux legacy migration](linux-legacy-migrated.png) | Visible converted KIRI fixture at `34a6797f4` |
| [Mac multiline composer](mac-composer-buffer.png) | Final `1a9e791e3` framebuffer layout and readable draft; not OS translucency evidence |
| [Mac legacy migration](mac-legacy-migrated.png) | Visible native cloud on the final normal build |
| [Mac CPU preview](mac-preview-cpu.png) | Final normal build's actual CPU result |
| [Windows native composer](windows-composer-native.png) | Reviewed AUTH-12 desktop at `34a6797f4`: preserved synthetic transcript/draft, neutral field and blurred scene behind sharp controls |

## Test results and limits

Affected standalone tests produced **629 passes and nine existing fixture
failures** in `tests/test_byok_models_cache.py`. Those unchanged fixtures omit
the auth token required by the existing catalog path; the failing node IDs
match the earlier baseline. Restricted loopback-bind failures were retried
outside that sandbox. This is not a full-suite green result.

Additional selections passed: native splats **71**, preview/device and adjacent
tests **80**, backend routing **69** (67 warnings), and install/overlay **19**
(10 platform skips). These selections overlap; do not sum their counts.

- **Windows:** remaining visual review is pending because automatic approval
  review rejected the canonical private S3 transit transfer twice. No bypass
  was attempted. State receipts for later glass/Vulkan/splat cases do not
  substitute for inspecting their screenshots. Directory ACL denial and
  owner-only ACL confinement remain untested; CUDA was disabled in this private
  build, so CUDA/OptiX and GPU Cycles are unqualified.
- **Linux:** OpenGL only; no Vulkan qualification. Root could not enforce the
  two KEY-22 chmod write-denial faults. Native captures establish color/layout,
  without a controlled backdrop probe. Early default-run frames caught EEVEE
  compiling; only settled frames support shaded-render claims.
- **Mac:** Cycles Metal hardware rendering remains unqualified. Three bounded
  controls—400 splats with CPU denoising, splats with GPU denoising, and a plain
  cube with GPU denoising—all exceeded 120 s in compiler preparation. Samples
  showed Metal compiler callbacks and device-readiness waits. Cache files
  progressed, but no render completed. This is not established as a
  splat-specific bug or harmless cold compilation; no 5.2 control was run.
- No real provider OAuth flow, paid generation, production-world stress test or comparative
  performance certification was attempted. Linux logs include cold drawing
  and QA screenshot stalls, reaching 5070 ms in the broad run.

## Isolation and retained evidence

Linux used only the owned private build and sandbox. All **32 other containers**
matched their baseline IDs, images, mounts, process states and timestamps,
including after the final preview follow-up. Shared client, Blender 5.2 and
library pins were unchanged. The four owned containers, app, QA port and display
were stopped. Windows' private checkout is clean, shared 5.2 pins are unchanged,
owned workers/tasks are gone, and all four QA lanes are released. The final
owned Mac process was also stopped.

[results.json](results.json) contains the sanitized state, revision, diagnostic
and isolation summary. Full run records remain in the local ignored
`build/qa/blender53-develop-447/` artifact tree. This folder contains no profiles,
credential stores, control tokens or raw observations. The
[earlier develop integration report](../blender53-develop-merge/README.md)
retains the preceding 4.4.5/4.4.6 scope.
