# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tool tooltips for a space without a tool system (overlay of
``startup/bl_ui/space_toolsystem_common.py``).

The tooltip of a tool button evaluates
``description_from_id(bpy.context, bpy.context.space_data.type, idname)`` and
iterates ``item_group_from_id(...)``. Drawn in an editor with no
``*_PT_tools_active`` panel, the first raised ``AttributeError: 'NoneType'
object has no attribute '_tool_get_by_id'`` (crash signature cc1baf12) and the
second ``TypeError: 'NoneType' object is not iterable`` (b04b2331).

The real functions run out of the overlay file against a stub panel helper.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "src/scripts/startup/bl_ui/space_toolsystem_common.py"


class _Helper:
    """``ToolSelectPanelHelper``: one tool editor, ``QA_EDITOR``, with no tools."""

    @staticmethod
    def _tool_class_from_space_type(space_type):
        return _Editor if space_type == "QA_EDITOR" else None


class _Editor:
    @classmethod
    def _tool_get_group_by_id(cls, context, idname, *, coerce=False):
        return None  # the tool is not in this editor

    @classmethod
    def _tool_get_by_id(cls, context, idname):
        return None, -1


def _functions(*names):
    tree = ast.parse(OVERLAY.read_text())
    body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(body) == len(names)
    ns = {"ToolSelectPanelHelper": _Helper}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(OVERLAY), "exec"), ns)
    return [ns[name] for name in names]


def test_description_is_empty_for_a_space_without_a_tool_system():
    (description_from_id,) = _functions("description_from_id")
    assert description_from_id(None, "PROPERTIES", "builtin.select_box") == ""


def test_item_group_is_empty_for_a_space_without_a_tool_system():
    (item_group_from_id,) = _functions("item_group_from_id")
    group = item_group_from_id(None, "PROPERTIES", "builtin.select_box", coerce=True)
    assert group == ()
    # What the tooltip evaluates:
    assert "\x00".join(item.idname for item in group if item is not None) == ""


def test_item_group_is_empty_for_a_tool_the_editor_does_not_have():
    (item_group_from_id,) = _functions("item_group_from_id")
    assert item_group_from_id(None, "QA_EDITOR", "builtin.missing", coerce=True) == ()


def test_a_missing_tool_in_a_tool_editor_still_reads_as_no_description():
    (description_from_id,) = _functions("description_from_id")
    assert description_from_id(None, "QA_EDITOR", "builtin.missing") == ""
