# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent-driven sculpt stroke replay (ViSculpt-style mesh editing).

Library module — no UI, no registration. The Mixar backend's
``modeling.sculpt`` agent lane synthesizes brush-stroke trajectories in
camera-image space (Smear / Drag / Draw primitives) and replays them here
through Blender's native sculpt stroke pipeline
(``bpy.ops.sculpt.brush_stroke``), so edits inherit built-in stroke
processing exactly as a human artist's strokes would.

Entry point: :func:`stroke_engine.apply_strokes` — invoked from a
backend-authored ``execute_bpy_script`` template
(``tools/scripts/sculpt/apply_brush_strokes.py`` in mixar-backend).

Pure coordinate math lives in :mod:`mapping` (no bpy import) so it is
unit-testable outside Blender.
"""
