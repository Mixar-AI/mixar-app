# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shift+M opens Mixie, replacing Blender's own Shift+M everywhere.

``bpy`` is a MagicMock here, so the operator and keymap wiring are pinned
from source (``ast``) and against Blender's default keymap file: every
default keymap that binds plain Shift+M must also carry our item, or that
editor would keep Blender's action.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OP_FILE = ROOT / "src/scripts/mixar/modules/agent_bubble/ui/operators/open_mixie_op.py"
DEFAULT_KEYMAP = ROOT / "upstream/scripts/presets/keyconfig/keymap_data/blender_default.py"

# km_* function in blender_default.py → the keymap name it builds.
KM_FUNCTION_NAMES = {
    "km_outliner": "Outliner",
    "km_object_mode": "Object Mode",
    "km_pose": "Pose",
    "km_edit_armature": "Armature",
}


def _module_constant(name):
    tree = ast.parse(OP_FILE.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found")


def _default_shift_m_keymaps():
    found, current = set(), None
    for line in DEFAULT_KEYMAP.read_text().split("\n"):
        m = re.match(r"def (km_\w+)\(", line)
        if m:
            current = m.group(1)
        if (re.search(r"\"type\": 'M'", line) and '"shift": True' in line
                and not re.search(r'"(ctrl|alt|oskey)": True', line)):
            found.add(current)
    return found


def test_every_default_shift_m_keymap_is_overridden():
    ours = {name for name, _space in _module_constant("SHIFT_M_KEYMAPS")}
    defaults = _default_shift_m_keymaps()
    assert defaults, "blender_default.py no longer binds Shift+M — revisit this test"
    unknown = defaults - set(KM_FUNCTION_NAMES)
    assert not unknown, f"new default Shift+M keymaps to cover: {unknown}"
    for fn in defaults:
        assert KM_FUNCTION_NAMES[fn] in ours, KM_FUNCTION_NAMES[fn]
    assert "Window" in ours   # every other editor


def test_keymaps_live_in_the_addon_keyconfig_with_plain_shift_m():
    src = OP_FILE.read_text()
    assert "wm.keyconfigs.addon" in src   # the keyconfig-reload rule
    assert "keymap_items.new(MIXAR_OT_open_mixie.bl_idname, 'M', 'PRESS',\n" in src
    call = src[src.index("keymap_items.new(MIXAR_OT_open_mixie.bl_idname"):]
    call = call[:call.index(")") + 1]
    assert "shift=True" in call
    assert not re.search(r"\b(ctrl|alt|oskey)=True", call)


def test_operator_always_claims_the_key():
    """A CANCELLED return would let the key fall through to Blender's own
    Shift+M item in the same keymap."""
    tree = ast.parse(OP_FILE.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
               and n.name == "MIXAR_OT_open_mixie")
    execute = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                   and n.name == "execute")
    returns = [n for n in ast.walk(execute) if isinstance(n, ast.Return)]
    assert returns and all(ast.literal_eval(r.value) == {'FINISHED'} for r in returns)
    src = ast.get_source_segment(OP_FILE.read_text(), execute)
    assert "agent_bubble_open_window" in src
    assert "mixar_bubble_tab = 'AGENT'" in src
    assert "_tabs_locked(wm)" in src   # Sketch / Voice own the tab strip


def test_help_menu_tutorials_replaces_about():
    topbar = (ROOT / "src/scripts/startup/bl_ui/space_topbar.py").read_text()
    menu = topbar[topbar.index("class TOPBAR_MT_help"):]
    menu = menu[:menu.index("\nclass ", 1)]
    assert 'text="Tutorials"' in menu
    assert "https://www.youtube.com/@Mixar3D" in menu
    assert "About Mixar" not in menu
