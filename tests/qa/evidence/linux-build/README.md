<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-2.0-or-later -->

# Ubuntu build validation

## Linux Agent Bubble follow-up

The rebuilt OpenGL app removes the Agent Bubble's native title bar and enforces
a 560 × 230 minimum size. `bubble-small-before.png` records the near-black
320 × 240 baseline; `bubble-small-after.png` shows the usable minimum after the
fix. `bubble-window-verdict.json` records six shrink/grow requests, native Motif
and frame properties, and an actual window-manager drag of 80 × 50 pixels.

`bubble-glass-red.png` and `bubble-glass-blue.png` capture the **presented X11
window**, including the live blurred parent viewport. Changing the viewport
background changes the visible backdrop. The tint shares Windows' 88% opacity
floor, and text/buttons remain opaque. Blender's ordinary offscreen screenshots
omit this final glass pass and cannot prove this behavior.

All 56 targeted Linux, window-shape, glass-lifecycle, transcript-opacity and
packaging checks pass. Replay on an idle X11/XWayland desktop (the test briefly
focuses its isolated window and moves the real pointer):

```bash
QA_HARNESS=/path/to/mixar-qa-harness \
  python3 tests/qa/linux_bubble_window.py
```

The runner forces X11 only for the app. Keep the desktop's `WAYLAND_DISPLAY`
in the runner environment so Ubuntu's XTest input bridge can deliver real
pointer events under XWayland.

Wayland uses native per-pixel alpha and suppresses Blender's client title bar
as well as requesting no server decorations. Its startup/Engine smoke passes;
compositor blur is not guaranteed, and the existing NVIDIA `EGL_BAD_ALLOC`
startup messages remain. The native drag/resize and live-blur regression above
was exercised on X11/XWayland. Non-OpenGL Linux paths retain opaque rendering.

## Initial build validation

The GCC 14 / Ninja Dev build completed on Ubuntu 26.04.1 using the pinned
Blender 5.2 source and Linux libraries. This local build uses CPU Cycles;
CUDA/OptiX remain enabled in the release workflow but were not tested here.

`verdict.json` records build inputs and test results. `render.png` is the
CPU Cycles output after saving and reopening a textured scene. `startup.png`,
`bubble.png`, and `engine.png` show the real app on the NVIDIA RTX 2050 under
X11/XWayland. The Engine screenshot follows a semantic click on the mode
switch and completion of first-use shader compilation. All images were
visually inspected. No authenticated backend requests were exercised.

Native Wayland also launched and drew the viewport, but logged EGL_BAD_ALLOC
while creating the floating Agent window. The X11/XWayland replay did not
log those errors; use `WAYLAND_DISPLAY=` as a local fallback on this setup.

The 19 targeted Linux, manifest and packaging tests pass. The full standalone
suite had 7,434 passes, 38 skips, 46 failures and 15 errors. The remaining
failures also reproduce on the unchanged merged base; upstream-dependent
checks were compared using the same Blender checkout. The two platform-guard
failures fixed by this PR fail on that base and pass here.

Reproduce the installed-build checks from the repository root:

```bash
MIXAR_USER_RESOURCES=/tmp/mixar-smoke-profile \
MIXAR_SMOKE_OUT=/tmp/mixar-smoke \
  build/Dev/bin/mixar --background --factory-startup --python-exit-code 1 \
  --python tests/qa/linux_build_smoke.py

QA_HARNESS=/path/to/mixar-qa-harness WAYLAND_DISPLAY= \
  python3 tests/qa/linux_gui_startup.py
```

The GUI replay uses an isolated profile, captures the viewport and Agent
window, clicks Engine mode, verifies its editors, captures the result, and
closes only the app it started. Omit `WAYLAND_DISPLAY=` to test the desktop's
default window system. `MIXAR_QA_BUILD`, `MIXAR_QA_PORT`, and `QA_SCENARIO_OUT`
override its build directory, local port and artifact root.

## Linux release workflow audit

The release, orchestrator, and publish workflows pass actionlint 1.7.7
(shellcheck integration disabled); seven manifest/packaging tests pass.
Shell syntax validation passes for the Linux packaging, checkpoint, upstream,
and archive-verification scripts.

Fixed three release gaps: Python smoke failures now propagate with
`--python-exit-code 1`; CI verifies the extracted archive before uploading it;
and upload selects the exact archive produced by this run instead of the first
archive in a potentially stale `dist/`. Added the explicit `xauth` dependency
needed by `xvfb-run` on minimal runners.

An intentional Python exception returned status 0 with the previous command
and status 1 with the corrected command. Packaged the current Dev installation
using `package_linux.sh`, including symbol stripping, into a 310,476,148-byte
archive. `verify-linux-archive.sh` extracted it to a temporary location and
passed version, runtime-import, packed-texture, save/reopen, and CPU Cycles
render checks. The verifier also rejects a missing archive.

This validates packaging with the Ubuntu 26.04 CPU Dev build. It does not
validate a full Ubuntu 24.04 CUDA/OptiX production build, S3 upload, or public
publishing. Repository AWS/S3 configuration names are present; credentials
and cloud access were not exercised. The inspected recent successful release
run (37741164514) built Windows only.
