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

## 2026-09-29 finding: the fork crashes before the lab can measure anything

On fork `feature/mixar-blastoff` (Blender 5.2.0 base) the lab segfaults in the depsgraph
relation builder on the third probe (`build_world` on a freed World), and the minimal
`probe_flip.py` (two scenes, one cube each, window switched between them, undo, redo)
segfaults at the REDO in `build_material → build_animdata → BKE_animdata_from_id`.
Stock Blender 4.2.21 runs `probe_flip.py` clean in both variants. No agents, no Python
handlers, no lane scenes: a plain bpy script. This is the crash class behind the
production Ctrl-Z crash of 2026-09-29 15:47, reduced to ten seconds. Evidence in
`~/Downloads/per-tab-undo/lab-29-09/evidence/` (probe_flip.py, crash logs, the stock run).
Determinism runs (same day): stock Blender 5.2.0 passes the full lab 2 of 3 times and
crashes the third; the production 4.1.2 bundle crashes `probe_flip.py` 1 of 2; the Dev build
crashes it 3 of 3. With `--debug-memory` (guarded allocator) the Dev crash disappears; with
Blender's legacy undo (`MIXAR_UNDO_LAB_LEGACY=1`) the full lab passes on Dev but the minimal
probe still crashes. So this is an allocation-order-dependent use-after-free in Blender's
multi-scene memfile undo/redo, present upstream, that the Dev build hits deterministically.
The harness is sound (all 16 document-mode checks pass whenever the build survives); the
next instrument is an ASAN build. Knobs for bisecting on a reference build:
`MIXAR_UNDO_LAB_NO_FURNISH`, `MIXAR_UNDO_LAB_NO_EDITMODE`, `MIXAR_UNDO_LAB_NO_B`,
`MIXAR_UNDO_LAB_LEGACY`.
