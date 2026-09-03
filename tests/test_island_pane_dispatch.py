# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One dispatcher behind every island pane's Generate.

A click and an Enter must resolve to the SAME paid generation. They did not:
the Media pane's button hardcoded ``mixie.imagegen_generate`` while Enter went
through ``core/prompt_submit.py``, which routes the ``depth_to_image`` mode —
a mode the island's own dropdown exposes — to ``mixie.lookdev_generate``.

The panes now invoke ``mixie.moodboard_prompt_generate`` with the tab
PropertyGroup's own RNA identifier, exactly the string
``interface_handlers.cc`` forwards for Enter, so the invariant is structural.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "src/source/blender/editors/space_agent_bubble"
OPS_PY = (
    ROOT
    / "src/scripts/mixar/modules/moodboard/ui/operators/prompt_generate_ops.py"
)

DISPATCHER = "mixie.moodboard_prompt_generate"
PANES = ("agent_ui_tab3d.cc", "agent_ui_tabmedia.cc", "agent_ui_tabsplat.cc")

# Generate operators the panes used to name directly. Any of these appearing
# in a pane again means that pane has forked away from the Enter routing.
FORKED_OPERATORS = (
    "mixie.imagegen_generate",
    "mixie.video_gen_generate",
    "mixie.model_gen_generate",
    "mixie.smart_segment_generate",
    "mixie.world_labs_generate",
    "mixie.lookdev_generate",
)


def test_every_pane_generates_through_the_shared_dispatcher():
    for name in PANES:
        source = (CPP / name).read_text()
        assert DISPATCHER in source, f"{name}: Generate does not use the dispatcher"


def test_no_pane_names_a_generate_operator_of_its_own():
    for name in PANES:
        source = (CPP / name).read_text()
        for operator in FORKED_OPERATORS:
            assert f'"{operator}"' not in source, (
                f"{name} calls {operator} directly — a click can then submit a "
                f"different paid generation than Enter does"
            )


def test_the_owner_type_comes_from_the_tab_struct_itself():
    """`RNA_struct_identifier` on the tab pointer is the same string the Enter
    handler forwards, so the two paths cannot drift; a hardcoded literal
    could."""
    for name in PANES:
        source = (CPP / name).read_text()
        block = source[source.index(DISPATCHER) :]
        owner = re.search(r'RNA_string_set\(op_ptr,\s*"owner_type",\s*([^)]+)\)', block)
        assert owner is not None, f"{name}: dispatcher call sets no owner_type"
        assert "RNA_struct_identifier(" in owner.group(1), (
            f"{name}: owner_type is not read off the tab PropertyGroup itself"
        )


def test_the_enter_handler_and_the_panes_agree_on_the_owner_string():
    handlers = (
        ROOT / "src/source/blender/editors/interface/interface_handlers.cc"
    ).read_text()
    assert "RNA_struct_identifier(but->rnapoin.type)" in handlers


# -------------------------------------------------------------------------
# The dispatcher itself must never be a silent dead end.


def _execute_body() -> ast.FunctionDef:
    tree = ast.parse(OPS_PY.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "execute":
            return node
    raise AssertionError("MIXIE_OT_moodboard_prompt_generate.execute not found")


def _is_cancelled(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Return)
        and isinstance(node.value, ast.Set)
        and any(
            isinstance(e, ast.Constant) and e.value == "CANCELLED"
            for e in node.value.elts
        )
    )


def _reports(nodes) -> bool:
    return any(
        isinstance(call.func, ast.Attribute) and call.func.attr == "report"
        for node in nodes
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
    )


def test_every_bail_out_tells_the_user_why():
    """Routed from a visible Generate button, a bare `{'CANCELLED'}` is a
    button that does nothing and says nothing."""
    execute = _execute_body()
    checked = 0
    for parent in ast.walk(execute):
        body = getattr(parent, "body", None)
        if not isinstance(body, list):
            continue
        for i, stmt in enumerate(body):
            if not _is_cancelled(stmt):
                continue
            checked += 1
            assert _reports(body[:i]), (
                f"line {stmt.lineno}: returns CANCELLED with no self.report"
            )
    assert checked >= 3, "expected the unresolved / missing / poll bail-outs"
