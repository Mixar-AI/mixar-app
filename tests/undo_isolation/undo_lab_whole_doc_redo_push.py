# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Undo Whole Document, a per-tab redo, then an edit: the redone step survives.

Headless, inside a built bundle (run by test_whole_doc_redo_push.py):

    MIXAR_PER_TAB_UNDO=1 Mixar --background --factory-startup --python <this>

Regression of 2026-10-15 (overnight blastoff run): after Undo Whole Document the
document's active step sits below a step the tab redoes, and the next push freed
that step — one undo then took back the edit AND the redone cube, and an edit
after that lost the cube for good. Prints one ``WDRP {json}`` line.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402

import undo_lab_core as L  # noqa: E402

L.build()


def has(name):
    return name in L.tab("C").objects


out = {}
L.edit("C", "C · add cube2", lambda: L.add_mesh(L.tab("C"), "C_cube2", "cube", (3, 3, 0)))
with L._override_window():
    bpy.ops.ed.undo_whole_document()
out["gone_after_whole_document"] = not has("C_cube2")
L.show("C")
L.press("redo")
out["back_after_tab_redo"] = has("C_cube2")
x0 = L.tab("C").objects["C_torus"].location.x


def move_torus():
    L.tab("C").objects["C_torus"].location.x += 2.0


L.edit("C", "C · move torus", move_torus)
L.press("undo")
out["undo_takes_back_only_the_move"] = (has("C_cube2")
                                        and abs(L.tab("C").objects["C_torus"].location.x - x0) < 1e-6)
L.edit("C", "C · add sphere", lambda: L.add_mesh(L.tab("C"), "C_sphere9", "sphere", (-3, 3, 0)))
out["cube_survives_a_new_edit"] = has("C_cube2")
print("WDRP " + json.dumps(out), flush=True)
bpy.ops.wm.quit_blender()
