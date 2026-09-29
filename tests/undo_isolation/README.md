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
or `build/Dev`): `document` with `MIXAR_PER_TAB_UNDO` off, `isolation` with it on. Both must
pass on the per-tab branch.

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

## 2026-09-29: M2 and M3 green behind `MIXAR_PER_TAB_UNDO=1`

The isolation contract is the build's behaviour with the flag on. P1–P4 (memfile steps,
M2), P5–P6 (edit-mode steps in C over A's memfile steps, M3) and three isolation-only
probes: P7 undo in C, a push in A, redo in C (C's redo survives another tab's push); P8 Edit
> Undo History jumps (`ed.undo_history(item=<stack index>)`, index from
`WindowManager.mixar_undo_history`) back to C's first edit and forward to its newest; P9
`undo_steps = 8`, twelve pushes in A, redo in C still works and C keeps eight of its own
steps (the per-tab reserve and the cursor pin in the step limit). 68 checks with the flag,
25 without. The `M3 P9 stack:` line prints the whole tagged stack after the limit ran.

## 2026-09-30: M4 green: the hold as a poll, Undo Whole Document

P10 registers the two run flags with `bpy.props` the way the chat module does (they land in
`id.system_properties`, the store the C side reads first) and checks the operators' polls in
C: its own run open, BUSY, AWAITING_INPUT or a raw custom property refuse undo, redo, history
and the whole-document entry; only A's run open leaves C free to undo but not to undo the
whole document; all idle allows everything. P11 runs `ed.undo_whole_document` (exec, no
dialog headless) after P9 left twelve A steps written while C stood one step back: A's newest
step AND C's redone object go, C's redo is alive, per-tab redo in A then in C brings both
back. 94 checks with the flag, 25 without. Fingerprints use `matrix_basis` (`matrix_world` is
evaluated data, reset by a full re-read until that scene's depsgraph runs).

## 2026-09-30: M5, on by default

The flag is on unless `MIXAR_PER_TAB_UNDO=0`; the pytest wrapper sets it to `0` for the
document contract. New isolation probes: P10e a window on a worker lane refuses everything;
P14 a global Text is left alone by a tab's undo; P13 the kill switch after a tab walk (the
classic undo re-reads every ID, no crash, the flag back on, every tab redone to its top);
P12 a closed tab stays closed under a tab's undo and comes back with the same `session_uid`
under Undo Whole Document. 112 checks with the flag, 25 without; the same 112 clean under
ASAN. The lab tolerates a tab that no longer exists (a closed tab is absent from the
fingerprint).
