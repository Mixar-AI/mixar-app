<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-2.0-or-later -->

# Blender 5.3 UI qualification follow-up

**In progress.** This report does not yet establish complete UI qualification.
The scope is the Agent island and pill, all eight tabs, composer editing and
focus, transcript navigation, native window movement and restoration, toolbar
scaling, menus, workspaces and Moodboard controls. Previous non-UI checks remain
in the [integration report](../blender53-develop-447/README.md).

Broad Mac and Windows checks use runtime `1a9e791e3` (Mixar 4.4.7, Blender 5.3).
Linux includes the verified X11 Vulkan transparency correction described below. All
profiles are disposable. These checks submit no paid chat or generation request.
The additional shared toolbar hit-region correction is `58b795ae6`; its Linux
and Windows targeted replays pass. The Mac candidate builds but has not yet run
that replay. These results are separate from the earlier UI pass.

## Findings and corrections

- Linux Vulkan selected an opaque island bed because the alpha request was
  limited to OpenGL. This limitation also exists in the 5.2 develop baseline.
  The correction requests an alpha-capable visual for X11 Vulkan and verifies
  a 32-bit TrueColor visual with an XRender alpha mask. Unsupported visuals
  retain the opaque fallback. Wayland Vulkan behavior is unchanged.
- A Moodboard Board-button click at 125% scale was intercepted by the right
  resize edge of Zen's fixed Move/Rotate/Scale toolbar. The native window
  geometry places both at x=486 in the failing Windows run. The edge policy
  matches the 5.2 baseline, so this is an inherited bug uncovered by testing.
  The correction suppresses only the visible overlapping Zen TOOLS resize
  zone; Engine resizing and hidden-toolbar reveal retain their existing policy.
  The compiled policy regression fails before the correction and passes after.
- The QA driver could dispatch a click from inside AppKit's native resize
  callback. A live failure recorded an active resize with a valid, unchanged
  owner lease and live target. The driver now defers its pump while resizing;
  the all-tabs replay subsequently passed. Queued and active gestures have
  focused regression tests. No input event is retried or lease check bypassed.
- The older broad replay used Escape to leave a text field. Escape cancels
  the current edit; a header click commits it. The replay now checks the exact
  three-line draft before and after committing. Add-on is explicitly included.
- Several older replay assumptions needed correction: Mac region capture was
  used on Windows generation panes, a compact Render Settings control was
  queried by a stale widget type, and an attachment-menu outside click could
  accidentally open a folder picker. Original failures remain evidence;
  corrected scenarios require fresh state and visual verification.

## Current platform evidence

| Platform | Established | Still pending |
| --- | --- | --- |
| macOS / Metal / Apple M4 | All eight tabs and scene drafts; Zen, Engine, Texturing and menus; real native pill/island drag and restore state; framebuffer images reviewed. Shared toolbar candidate builds successfully | Complete native compositor screenshot series, final composer interaction and shared-toolbar GUI replays |
| Linux / NVIDIA L4 / X11 | OpenGL and Vulkan native compositor, lifecycle and broad UI pass; 88 original screenshots reviewed. Subsequent shared-toolbar fix passes its targeted OpenGL replay with 17 native originals reviewed; both cleanup receipts verified | None within this matrix; Wayland Vulkan remains unqualified |
| Windows / Tesla T4 / Vulkan | Ten final cases pass state and scoped vision: tabs, scene drafts, composer, menus/workspaces, Moodboard controls/help and shared-toolbar fix. All final images accounted for; owned cleanup and four lane releases verified | None within this matrix; known visibility limits remain below |

The [Linux results](linux-results.json) record the exact binary and native source
hashes, before/after blur measurements, reviewed image counts and isolation checks.
The Vulkan [opaque baseline](linux-vulkan-before.png), corrected
[expanded island](linux-vulkan-after.png) and [pill](linux-vulkan-pill-blue.png),
and the [OpenGL committed draft](linux-opengl-idle-draft.png) are unchanged native
desktop originals. All four cases pass. Both owned applications, private displays
and the window-manager helper were stopped; 32 other containers and the shared
Blender 5.2 pins were unchanged. Forty-two focused tests passed. Unequal startup
and diagnostic runs recorded residual UI stalls, so these results do not certify
performance or claim a zero-stall run.

The subsequent [Linux toolbar results](linux-toolbar-results.json) identify exact
candidate `58b795ae6` and its binary hash. The visible Board button opens on the
underlying toolbar edge at all three requested UI scales, Move → Rotate and grip
transitions work, and Engine's toolbar expands then returns to its original
width. The [125% menu](linux-board-125-fixed.png) and
[settled Engine view](linux-engine-resize-fixed.png) are native originals.
The compiled policy test passes after failing on the old implementation. The
broader targeted unit selection has 33 passes and one existing palette assertion
failure: the test expects `CinemaPillOnB`, while unchanged drawer code uses
`Selected`. That failure is unrelated to this correction and is retained.

Mac Screen Recording remains disabled at the user's request. The harness stages
controlled views and records owned-process identity, native material and geometry;
the user supplies native screenshots. The first red-backdrop image shows tinted,
blurred background beneath sharp controls. A red/blue pair and bright/dark
readability views are still required. Framebuffer images are not native glass
evidence, and a manually supplied screenshot is not an automatically synchronized
native capture.

The first Windows workflow review accounts for 115 PNG paths: 111 distinct
images and four exact duplicates. All images were reviewed in indexed sheets
(native pixel size for island/pill, scaled layouts), with four full original
desktop views checked separately. That replay stopped at its stale Render
Settings query; it is not a complete workflow pass. The corrected UI11 review
covered 149 paths / 108 distinct originals and identified the accidental picker,
so its original state-pass result is explicitly rejected as a full pass.
The final workflow passes and its 56 paths / 54 distinct images were reviewed
(48 newly distinct images and six exact matches to previously reviewed images).
The final UI11 passes 28 assertions; its 146 paths / 110 distinct images were
reviewed. Disconnected-send notifications remain partly hidden behind the island;
the relevant notification layout code matches the 5.2 baseline. Moodboard's tiny
new-node hint is also difficult to read until Frame Selected enlarges the node.
These limitations are retained rather than described as fully readable UI.

Selected unchanged native originals show the Windows
[committed draft](windows-idle-draft.png), [125% tooltip](windows-tooltip-125.png),
[compact Texturing layout](windows-texturing-compact.png) and
[Splats tab](windows-splats-tab.png). The latter uses a local QA catalog fixture,
not a provider submission. The [Mac red backdrop](mac-red-native-user.png) is the
user-supplied image; it is only one stage of the pending manual series.
[Hashes and capture scope](selected-screenshots.json) accompany these originals.

[Windows results](windows-results.json) and [detailed scope](windows-details.md)
account for all 687 final PNG paths / 603 distinct contents through visual review
and exact-hash or pixel-verified derivatives. Historical diagnostic images are
not all reviewed and supply no final pass claim. The corrected
[125% Board menu](windows-board-125-fixed.png) and preserved
[Engine toolbar resizing](windows-engine-resize-fixed.png) run on `58b795ae6`.
Both parameter-help hosts also pass with the underlying toolbar visible.
All owned apps/tasks stopped, all four lanes were released, and shared Blender
5.2 pins stayed unchanged. Startup, screenshot instrumentation and observed
Engine drawing stalls are distinguished in the detailed report.

## Replay entry points

- [Broad UI](../../blender53_visual_ui_e2e.py), including Add-on and committed draft checks.
- [Linux compositor](../../linux_compositor_e2e.py) and [Linux wider UI](../../linux_visual_ui_e2e.py).
- [Mac native compositor](../../mac_native_compositor_e2e.py), which requires an existing capture permission.
- [Manual Mac staging](../../mac_manual_native_ui_e2e.py), which never requests Screen Recording and never marks its own screenshots reviewed.
- [Windows native capture wrapper](../../windows_ui_capture.py) and [Windows workflow](../../windows_workflow_ui_e2e.py).
- [Shared toolbar routing](../../windows_moodboard_hit_zones_e2e.py), named for its first host but tested on Windows and Linux. The companion harness's BOARD-20 adapter adds strict grip/Engine restoration checks against its receipts; those checks pass on both saved runs.

[Harness PR #80](https://github.com/Mixar-AI/mixar-qa-harness/pull/80) includes
the resize-dispatch guard and replay bindings. Mac's automatic native capture
case requires an existing Screen Recording grant and cannot pass from manual
images or framebuffer substitutes. The manual staging and capture helpers have
16 passing ownership, permission and failure-cleanup tests; these are not a
native GUI verdict.

Full local run records, original diagnostics, screenshot hashes and review
manifests are retained under ignored `build/qa/blender53-ui-completion/`.
Selected evidence and Windows/Linux cleanup receipts are recorded above. Mac
native visual proof, remaining interactions and its owned app cleanup are pending.
