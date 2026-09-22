# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""The Mixie node pie is bound to Ctrl+Tab alone; the backtick stays the drawer's.

Source-level pin: keymap registration runs inside Blender, so the binding
calls are inspected with ``ast`` instead of being executed.
"""

import ast
from pathlib import Path


KEYMAP = Path(__file__).parents[2] / "src/scripts/mixar/modules/moodboard/ui/keymap.py"
PIE_OP = "mixie.moodboard_pie_menu_call"
DRAWER_OP = "view3d.moodboard_drawer_toggle"


def _const(node):
    return node.value if isinstance(node, ast.Constant) else node


def _bindings(tree):
    """Every ``<km>.keymap_items.new(...)`` call as (idname, kwargs)."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "new"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "keymap_items"):
            continue
        kwargs = {kw.arg: _const(kw.value) for kw in node.keywords if kw.arg}
        positional = [_const(a) for a in node.args]
        idname = kwargs.get("idname", positional[0] if positional else None)
        if len(positional) > 1:
            kwargs.setdefault("type", positional[1])
        if len(positional) > 2:
            kwargs.setdefault("value", positional[2])
        found.append((idname, kwargs))
    return found


def test_pie_menu_binds_only_ctrl_tab():
    tree = ast.parse(KEYMAP.read_text())
    pie = [kwargs for idname, kwargs in _bindings(tree) if idname == PIE_OP]
    assert len(pie) == 1, pie
    (kwargs,) = pie
    assert kwargs["type"] == "TAB"
    assert kwargs["value"] == "PRESS"
    assert kwargs["ctrl"] is True
    assert not any(kwargs.get(mod) for mod in ("shift", "alt", "oskey"))


def test_backtick_belongs_to_the_drawer_toggle_alone():
    tree = ast.parse(KEYMAP.read_text())
    grave = [(idname, kwargs) for idname, kwargs in _bindings(tree)
             if kwargs.get("type") == "ACCENT_GRAVE"]
    assert grave, "the drawer toggle must still bind ACCENT_GRAVE"
    assert {idname for idname, _ in grave} == {DRAWER_OP}, grave
    # Nothing binds the pie through a computed key either.
    for idname, kwargs in _bindings(tree):
        if idname == PIE_OP:
            assert isinstance(kwargs["type"], str), kwargs


def test_user_view_pie_key_lookup_is_gone():
    text = KEYMAP.read_text()
    tree = ast.parse(text)
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "get_user_pie_menu_key" not in names
    assert "get_user_pie_menu_key" not in text
    assert "VIEW3D_MT_view_pie" not in text
