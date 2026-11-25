# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Texel Density Units change recalculates only when Calculate TD can run.

Calculate TD's execute() leaves and re-enters the active object's mode, so its
poll requires mode_set's poll (a hidden, linked or missing active object fails
it) and also refuses an object hidden in viewports, which mode_set's poll lets
through in Edit Mode but which cannot re-enter Edit Mode. The Units update
callback checks that poll before running the operator.
bpy is a MagicMock outside Blender, so both functions are lifted from source
with ``ast`` and executed against a fake ``bpy.ops``.
"""

import ast
from pathlib import Path
import textwrap
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

TEXEL = Path(__file__).resolve().parents[1] / "src/scripts/mixar/modules/texel_density/texel"
PROPS = (TEXEL / "props.py").read_text(encoding="utf-8")
OPERATORS = (TEXEL / "core_td_operators.py").read_text(encoding="utf-8")


def _load(module, name, cls=None):
    scope = ast.parse(module).body
    if cls:
        scope = next(n for n in scope if isinstance(n, ast.ClassDef) and n.name == cls).body
    node = next(n for n in scope if isinstance(n, ast.FunctionDef) and n.name == name)
    check = Mock(return_value={"FINISHED"})
    mode_set = Mock()
    ns = {"bpy": NS(ops=NS(texel_density=NS(check=check), object=NS(mode_set=mode_set)))}
    exec(textwrap.dedent(ast.get_source_segment(module, node)), ns)
    return ns[name], check, mode_set


@pytest.mark.parametrize("can_run", [True, False])
def test_change_units_runs_check_only_when_it_polls(can_run):
    change_units, check, _ = _load(PROPS, "change_units")
    check.poll.return_value = can_run
    change_units(None, None)
    assert check.call_count == (1 if can_run else 0)


@pytest.mark.parametrize(
    ("editable", "hide_viewport", "expected"),
    [(True, False, True), (False, False, False), (True, True, False)],
)
def test_check_poll_needs_mode_set_poll_and_a_viewport_visible_object(editable, hide_viewport, expected):
    poll, _, mode_set = _load(OPERATORS, "poll", cls="TexelDensityCheck")
    mode_set.poll.return_value = editable
    context = NS(active_object=NS(hide_viewport=hide_viewport))
    cls = NS(poll_message_set=Mock())
    assert poll(cls, context) is expected
    if editable and hide_viewport:
        cls.poll_message_set.assert_called_once_with("Active object is hidden in viewports")
    else:
        cls.poll_message_set.assert_not_called()
