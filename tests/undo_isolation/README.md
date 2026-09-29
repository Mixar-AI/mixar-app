# Per-tab undo: isolation lab (design M0)

`undo_isolation_lab.py` runs INSIDE a built Mixar bundle, headless:

```bash
MIXAR_UNDO_LAB_EXPECT=document build/Dev/bin/Mixar.app/Contents/MacOS/Mixar \
  --background --factory-startup --python tests/undo_isolation/undo_isolation_lab.py
```

It builds three scene tabs with disjoint datablocks (C manual, A and B agent-like with
bracketed turns), interleaves their steps on the one undo stack, then undoes / redoes with
the window on C and fingerprints every tab before and after each press. `report.json` lands
in `MIXAR_UNDO_LAB_OUT` (default `/tmp/mixar-undo-lab`); one `M0 <probe> / <check>: PASS|FAIL`
line per expectation.

Two contracts: `document` (what a document-wide undo does: the press reverts A's newest
turn and moves the window) and `isolation` (the per-tab design: only C moves, the window
stays). `test_undo_isolation.py` runs both through pytest when a bundle exists (`MIXAR_APP`
or `build/Dev`), `isolation` as a non-strict xfail until the flag ships.

## 2026-09-29: green on the current build, after one harness bug

First runs crashed the fork, the production bundle and stock Blender 5.2.0 intermittently
in the depsgraph after an undo or a redo. An ASAN build named the freed block: the Scene the
lab had pinned into the context with `temp_override(scene=…, view_layer=…)` around
`ed.undo` / `ed.redo`. A Python context override is a raw pointer; the memfile decode
replaces the Main and frees the old Scene, then the operator wrapper's post-call view-layer
update (`bpy_op_view_layer_update`) reads the stale override. Undo, redo and `undo_push`
therefore run under `temp_override(window, screen)` only. With that, the Dev build passes
the minimal probe 3/3 and the full lab 3/3 (16 of 16 document-mode checks), and
`test_document_wide_undo_is_what_the_build_does_today` is green. The production Ctrl-Z
crash of the same day went through the key-event path with no override and is NOT
reproduced by this lab; the GUI scenario in the QA harness plus the ASAN bundle is the
instrument for it. Knobs for bisecting: `MIXAR_UNDO_LAB_NO_FURNISH`,
`MIXAR_UNDO_LAB_NO_EDITMODE`, `MIXAR_UNDO_LAB_NO_B`, `MIXAR_UNDO_LAB_LEGACY`.
