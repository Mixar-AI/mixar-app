# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Procedural assembly compiler (Procedura-style shape-as-code modeling).

Library module — no UI, no registration. The Mixar backend's
``modeling.assembly`` agent lane maintains a parametric assembly PROGRAM (a
constrained Python DSL, one named module per physical part, parts joined by
typed machine-checkable mates) and compiles it here: parts are realized as
Blender objects via exact-solver CSG booleans, each part's placement is
SOLVED from its mate frames (never guessed by the model), the mate macros
emit both halves of every joint from one shared nominal dimension plus a
fit-class offset, and a deterministic measurement suite (mate registration
area, penetration depth, union-find span-based floater analysis) reports
back so the backend can gate every commit.

Entry points (invoked from backend-authored ``execute_bpy_script`` bridge
templates — ``tools/scripts/assembly/*.py`` in mixar-backend):

- :func:`compiler.compile_assembly` — validate + execute the program in the
  routed (lane) scene, measure, and return a compact JSON-safe report.
- :func:`render.render_assembly_views` — parts-colour multi-view captures
  from a fixed viewpoint catalog (Workbench object-color, or EEVEE material
  shading for the materials critic).
- :func:`materials.apply_part_materials` — per-part PBR assignment honouring
  the platform base-colour contract (Principled base color + diffuse_color).

Pure transform/spec math lives in :mod:`frames` and :mod:`spec` (no bpy
import) so it is unit-testable outside Blender. Paper reference: arXiv
2608.26238 ("Procedura: Agentic 3D Modeling with Procedural Control").
"""
