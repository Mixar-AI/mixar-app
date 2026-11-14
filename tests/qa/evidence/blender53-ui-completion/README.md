<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-2.0-or-later -->

# Blender 5.3 UI qualification follow-up

**Complete within the requested UI matrix on macOS, Linux and Windows.**
State assertions, visual review, replay artifacts and owned-app cleanup are
recorded below. This is not certification of the full release suite.
The scope is the Agent island and pill, all eight tabs, composer editing and
focus, transcript navigation, native window movement and restoration, toolbar
scaling, menus, workspaces and Moodboard controls. Previous non-UI checks remain
in the [integration report](../blender53-develop-447/README.md).

Broad Mac and Windows checks use runtime `1a9e791e3` (Mixar 4.4.7, Blender 5.3).
Linux includes the verified X11 Vulkan transparency correction described below. All
profiles are disposable. These checks submit no paid chat or generation request.
The additional shared toolbar hit-region correction is `58b795ae6`; its Linux
and Windows targeted replays pass. Mac
composer and toolbar replays also pass on that exact product revision. These
results are separate from the earlier UI pass.

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
- Immediately after recreating the Mac island, AppKit and WindowServer briefly
  disagreed on its geometry. The first staging attempt failed and restored all
  fixtures. The observer now waits up to three seconds for two agreeing native
  snapshots before setting a frame; ownership failures still stop immediately
  and no input action is retried. Fresh staging succeeds and its user screenshot is reviewed.
- On tall Retina windows, the Engine replay originally dragged in the empty
  tail below the toolbar. Blender clips resize hits to its visible content,
  using the same policy as 5.2. The replay now uses an observed toolbar-button
  row; the live diagnostic admits `SCREEN_OT_region_scale` and the unchanged
  resize/restore assertions pass. No product change was needed.
- Composer targets can briefly disappear from QA exports during relayout.
  Bounded read-only readiness now precedes one text event; no click or text
  action is retried. Companion captures retain one owned full-window framebuffer
  plus a GPU-region supplement, with no automatic native capture.

## Current platform evidence

| Platform | Established | Still pending |
| --- | --- | --- |
| macOS / Metal / Apple M4 | All eight tabs and scene drafts; Zen, Engine, Texturing and menus; native pill/island drag and restore. Eight user-supplied native screenshots cover island/pill backdrop response, recreation, bright/dark transcript readability and normal scene restoration. Final composer and three-scale toolbar state plus visual checks pass; owned app and listener stopped | None within this matrix; known limits remain explicit |
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
the user supplies native screenshots. The reviewed red/blue pair shows the island
changing tint with the backdrop, strongly attenuating the fine bands beneath it
and retaining sharp foreground controls. Four unchanged control/chrome anchors
confirm the framing offset between the images; no resizing or warping is used.
The [scoped visual review](mac-red-blue-visual-review.json) and
[descriptive pixel measurements](mac-red-blue-metrics.json) preserve the limits:
these are uncalibrated screenshot values, not optical transmittance or an
automatic capture pass. The [complete manual series](mac-manual-series-review.json)
accounts for all eight unchanged originals: red/blue island, recreated island,
bright/dark populated transcript, red/blue resting pill and restored normal scene.
The first five run on `1a9e791e3`; the final three run on `58b795ae6`. The
recreated native frame was set through the owned AppKit fixture, not a claim of
a human resize. Fixture cleanup restored both frames, the hover timer, handlers
and transcript, and removed its namespaces. Framebuffers cannot establish
native glass behavior; manual images do not automatically pass UI-25.

The bright view exposes pale Move/Rotate/Scale glyphs against their pale bed.
The [contrast review](mac-toolbar-contrast-review.json) records byte-identical
5.2/5.3 drawing policy and the same appearance in Linux evidence. This is an
observed inherited-policy limitation, without a 5.2 runtime A/B or formal
accessibility certification. The dark/normal views remain readable. Tooltips
partly cover the input in the dark image and bottom controls in the normal image;
those covered pixels are not used as readability proof.

The [final Mac results](mac-results.json) identify the exact binary and replay
hashes. UI11 passes all 28 composer checks with zero transport attempts. Its
[visual review](mac-composer-review.json) covers all 56 PNG paths / 47 distinct
contents: 42 match previously reviewed originals and all five new contents were
opened. The retained capture helper produces 28 ownership/hash receipts. The
[reopened composer](mac-composer-reopened.png) and [Attach menu](mac-composer-attach.png)
are unchanged application captures. A sequential Rules field-height difference
remains documented; the earliest wrapper-run blank engine chip does not recur
in the retained-helper run. Notifications are not visually qualified here.

The [Mac toolbar review](mac-toolbar-review.json) covers 18 PNG paths / 13 distinct
originals, with five exact duplicates. The [125% Board popup](mac-board-125-fixed.png)
is readable, tool/grip actions pass, and the [Engine toolbar](mac-engine-resize-fixed.png)
expands and restores at edges 904 → 984 → 904. At 125/150%, screenshots already
show Rotate selected before the click; state assertions prove the actions while
the images establish the final appearance. The Mac replays record capture/pump
stalls, with exact counts in the results, and do not certify zero latency.

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
not a provider submission. The [Mac red backdrop](mac-red-native-user.png) and
[blue backdrop](mac-blue-native-user.png) are unchanged user-supplied originals;
their reviewed pair covers the empty-island stage. The remaining originals show
[recreation](mac-recreated-native-user.png), [bright](mac-bright-native-user.png) /
[dark](mac-dark-native-user.png) readability, [red pill](mac-pill-red-native-user.png) /
[blue pill](mac-pill-blue-native-user.png), and the [normal scene](mac-normal-native-user.png).
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
- [Shared toolbar routing](../../windows_moodboard_hit_zones_e2e.py), named for its first host but tested on Windows, Linux and Mac. The companion harness's BOARD-20 adapter adds strict grip/Engine restoration checks against its receipts; those checks pass on the saved Windows/Linux runs and the final live Mac run.

[Harness PR #80](https://github.com/Mixar-AI/mixar-qa-harness/pull/80) includes
the resize-dispatch guard and replay bindings. Mac's automatic native capture
case requires an existing Screen Recording grant and cannot pass from manual
images or framebuffer substitutes. The manual staging and capture helpers have
20 passing ownership, permission, geometry-settling and failure-cleanup tests; these are not a
native GUI verdict.

Full local run records, original diagnostics, screenshot hashes and review
manifests are retained under ignored `build/qa/blender53-ui-completion/`.
Selected evidence and all three platforms’ cleanup receipts are recorded above.
The Mac controller stopped owned PID 85143; independent process/listener checks
confirm it and port 4814 are gone. Temporary namespaces and GPU capture handlers
were absent before shutdown; original UI scale was restored to 1.0.
