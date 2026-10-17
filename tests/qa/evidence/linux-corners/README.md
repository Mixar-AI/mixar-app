<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-2.0-or-later -->

# Linux rounded corners and desktop QA

The Ubuntu OpenGL build now applies the same 14-unit corner radius as Windows.
X11 clips the native bounding and input regions after every actual size change.
The final GPU pass clears all four corner pixels after the glass pass, preventing
the rectangular blur from filling them back in. Wayland also gets a rounded
input region, with logical coordinates converted separately from pixel rendering.

Compare [before](../linux-build/bubble-glass-blue.png) with
[the presented rounded window](rounded-window.png). This is a native RGBA
window capture: all four corner alpha values are zero, while the top edge past
the radius and the client interior remain opaque. It includes the live glass
pass that ordinary offscreen screenshots omit.

`native-window-verdict.json` records bounding/input shape checks across six
sizes, a real header drag (80 × 50 pixels), native resize through the product
operator, and live background color changes. An additional Linux-only bug was
fixed: `bubble_set_size` previously returned success while doing nothing.

`desktop-verdict.json` contains passing QA-harness results for:

- Header/menu geometry at UI scales 0.8, 1.0, 1.25, 1.5 and 2.0.
- Local Library assets and media: responsive layouts, larger fonts, filtering,
  sorting, adding an asset to the scene and selecting generated media.
- Attachment chooser, file-picker cancellation, image/folder references,
  scrolling and removal, including Unicode directory names.
- Viewport object creation, render/sample controls, guides/X-ray, playback,
  sky controls, OBJ export/cancel, compact controls, saved scene persistence
  and Zen/Engine switching.
- Packed texture save/reopen and CPU Cycles rendering.

All 56 targeted Python checks pass. Screenshots for the minimum-width Library,
mixed references and compact toolbar were visually inspected. No paid backend
requests were made.

Harness corrections exposed during the review: activate the X11 test window
through the WM before dragging; retain the runner's Wayland display for Ubuntu's
XTest bridge; respect Linux's 560px floor; recognize local PNG library items;
select the shading popover instead of an arbitrary first popover; and use the
current adaptive icon-only controls. These were test assumptions, not newly
introduced product failures.

Reproduce on an idle desktop, with Pillow and libXtst installed:

```bash
QA_HARNESS=/path/to/mixar-qa-harness python3 tests/qa/linux_bubble_window.py
QA_HARNESS=/path/to/mixar-qa-harness WAYLAND_DISPLAY= python3 tests/qa/linux_desktop_e2e.py
```

The native test briefly focuses its own isolated window and moves the pointer.
Keep the runner's `WAYLAND_DISPLAY`; it forces X11 only in the app subprocess.

Native Wayland startup and Engine switching are checked separately with
`tests/qa/linux_gui_startup.py`. NVIDIA still logs the existing `EGL_BAD_ALLOC`
startup warnings; X11/XWayland is the verified path for native corner/drag/glass
testing. Authenticated backend jobs and Vulkan transparency remain outside
this validation.
