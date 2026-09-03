# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A generation that refuses must say so, in the island as well as the N-panel.

The island's panes run their Generate through
``mixie.moodboard_prompt_generate``, which calls the real operator via
``bpy.ops``. ``bpy_operator.cc`` gives every nested call its OWN ReportList
("Own so these don't move into global reports"), so a nested report never
reaches the window manager's report list — which is exactly what the island
reads. Only ``{'ERROR'}`` escapes, because ``BPy_reports_to_error`` turns
error-level reports into a ``RuntimeError`` the dispatcher catches and
re-reports itself.

So a precondition failure reported as ``{'WARNING'}`` is silently swallowed and
the Generate button does nothing at all. Blender's own convention agrees with
the fix: a WARNING means "it worked, with caveats"; an operator that could not
do its job reports ERROR.

This pins the level for every operator reachable from ``PROMPT_TAB_DISPATCH``
(``moodboard/core/prompt_submit.py``, the authoritative list) plus the two
footer tables it resolves through.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"
OPS = MOODBOARD / "ui/operators"
DISPATCHER_PY = OPS / "prompt_generate_ops.py"

# bl_idname -> module holding it. Every entry is reachable from
# PROMPT_TAB_DISPATCH: directly, or through _MODEL_GEN_FOOTER /
# _TEXTURE_GEN_FOOTER, which the dispatch resolvers mirror.
GENERATE_OPERATORS = {
    "mixie.imagegen_generate": "imagegen_ops.py",
    "mixie.lookdev_generate": "lookdev_ops.py",
    "mixie.lookdev360_generate": "lookdev360_generate_op.py",
    "mixie.texture_edit_generate": "texture_gen_ops.py",
    "mixie.texture_gen_matgen": "texture_gen_ops.py",
    "mixie.pbr_gen_generate": "pbr_gen_ops.py",
    "mixie.image_to_3d_generate": "image_to_3d_ops.py",
    "mixie.model_gen_generate": "model_gen_ops.py",
    "mixie.smart_segment_generate": "segment_gen_ops.py",
    "mixie.mesh_segment_submit": "mesh_segment_ops.py",
    "mixie.video_gen_generate": "video_gen_ops.py",
    "mixie.world_labs_generate": "world_labs_ops.py",
    "mixie.scene_recon_generate": "scene_recon_ops.py",
}


# -------------------------------------------------------------------------
# The dispatch list is the scope, so drift in it must fail here too.


def test_the_dispatch_list_is_covered():
    source = (MOODBOARD / "core/prompt_submit.py").read_text()
    tree = ast.parse(source)
    table = next(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            getattr(t, "id", "") == "PROMPT_TAB_DISPATCH" for t in node.targets
        )
    )
    # Every _static("...") target in the table must be an operator we pin.
    statics = {
        call.args[0].value
        for call in ast.walk(table)
        if isinstance(call, ast.Call)
        and getattr(call.func, "id", "") == "_static"
        and call.args
        and isinstance(call.args[0], ast.Constant)
    }
    assert statics, "PROMPT_TAB_DISPATCH grew no _static entries — table moved?"
    missing = statics - set(GENERATE_OPERATORS)
    assert not missing, (
        f"PROMPT_TAB_DISPATCH routes to {sorted(missing)}, which this test does "
        f"not pin — a new pane's Generate can fail silently in the island"
    )


def test_the_footer_tables_are_covered():
    """Enter and the island's button both resolve through these tables, so an
    operator added to one is reachable from a pane the same day."""
    model_gen = (MOODBOARD / "ui/model_gen_drawer.py").read_text()
    texture_gen = (MOODBOARD / "ui/texture_gen_drawer.py").read_text()
    for source, name in ((model_gen, "_MODEL_GEN_FOOTER"),
                         (texture_gen, "_TEXTURE_GEN_FOOTER")):
        tree = ast.parse(source)
        table = next(
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(getattr(t, "id", "") == name for t in node.targets)
        )
        targets = {
            const.value
            for const in ast.walk(table)
            if isinstance(const, ast.Constant)
            and isinstance(const.value, str)
            and const.value.startswith("mixie.")
        }
        assert targets, f"{name} names no operators — table moved?"
        missing = targets - set(GENERATE_OPERATORS)
        assert not missing, (
            f"{name} routes to {sorted(missing)}, which this test does not pin"
        )


# -------------------------------------------------------------------------
# No precondition failure may be reported as a WARNING.


def _report_level(stmt) -> str | None:
    """The single level string of a bare ``self.report({'X'}, ...)`` statement."""
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
        return None
    call = stmt.value
    if not (
        isinstance(call.func, ast.Attribute) and call.func.attr == "report"
    ):
        return None
    if not call.args or not isinstance(call.args[0], ast.Set):
        return None
    elts = call.args[0].elts
    if len(elts) != 1 or not isinstance(elts[0], ast.Constant):
        return None
    return elts[0].value


def _is_cancelled(stmt) -> bool:
    return (
        isinstance(stmt, ast.Return)
        and isinstance(stmt.value, ast.Set)
        and any(
            isinstance(e, ast.Constant) and e.value == "CANCELLED"
            for e in stmt.value.elts
        )
    )


def _bodies(node):
    """Every statement list under ``node``, compound statements included."""
    for child in ast.walk(node):
        for field in ("body", "orelse", "finalbody"):
            body = getattr(child, field, None)
            if isinstance(body, list) and body and isinstance(body[0], ast.stmt):
                yield body


def _operator_class(module: ast.Module, idname: str) -> ast.ClassDef:
    for node in ast.walk(module):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if (
                isinstance(stmt, ast.Assign)
                and any(getattr(t, "id", "") == "bl_idname" for t in stmt.targets)
                and isinstance(stmt.value, ast.Constant)
                and stmt.value.value == idname
            ):
                return node
    raise AssertionError(f"no operator class declares bl_idname {idname!r}")


def _precondition_warnings(function: ast.FunctionDef):
    """WARNING reports immediately followed by ``return {'CANCELLED'}``."""
    found = []
    for body in _bodies(function):
        for i, stmt in enumerate(body[:-1]):
            if _report_level(stmt) != "WARNING":
                continue
            if _is_cancelled(body[i + 1]):
                found.append(stmt.lineno)
    return found


def test_no_generate_operator_warns_and_then_cancels():
    checked = 0
    for idname, module_name in GENERATE_OPERATORS.items():
        path = OPS / module_name
        cls = _operator_class(ast.parse(path.read_text()), idname)
        for fn in cls.body:
            if not isinstance(fn, ast.FunctionDef):
                continue
            if fn.name not in ("execute", "invoke", "_resolve_image"):
                continue
            checked += 1
            offenders = _precondition_warnings(fn)
            assert not offenders, (
                f"{module_name}:{offenders} — {idname}.{fn.name} reports "
                f"{{'WARNING'}} then returns CANCELLED. A nested bpy.ops call "
                f"keeps its own ReportList, so only {{'ERROR'}} reaches the "
                f"island; this refusal is invisible there."
            )
    assert checked >= len(GENERATE_OPERATORS), (
        "expected at least one execute/invoke per pinned operator"
    )


def test_the_generate_operators_still_report_their_refusals():
    """The fix is the LEVEL, not deleting the message: a silent CANCELLED is
    the same bug wearing a different hat."""
    for idname, module_name in GENERATE_OPERATORS.items():
        path = OPS / module_name
        cls = _operator_class(ast.parse(path.read_text()), idname)
        execute = next(
            fn for fn in cls.body
            if isinstance(fn, ast.FunctionDef) and fn.name == "execute"
        )
        errors = [
            stmt.lineno
            for body in _bodies(execute)
            for i, stmt in enumerate(body[:-1])
            if _report_level(stmt) == "ERROR" and _is_cancelled(body[i + 1])
        ]
        assert errors, (
            f"{module_name}: {idname}.execute has no ERROR-then-CANCELLED "
            f"refusal left — its preconditions went silent"
        )


# -------------------------------------------------------------------------
# The dispatcher re-reports what escapes, at the right level and undoubled.


def _dispatcher_handler() -> ast.ExceptHandler:
    tree = ast.parse(DISPATCHER_PY.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if getattr(node.type, "id", "") == "RuntimeError":
            return node
    raise AssertionError("prompt_generate_ops.py catches no RuntimeError")


def test_the_dispatcher_re_reports_escaped_errors_as_errors():
    """``BPy_reports_to_error`` is the only way a nested report reaches us, and
    it arrives as a RuntimeError. Re-reporting it as a WARNING would paint a
    stopped generation in the wrong colour."""
    handler = _dispatcher_handler()
    levels = [
        level
        for stmt in ast.walk(handler)
        if (level := _report_level(stmt)) is not None
    ]
    assert levels == ["ERROR"], (
        f"the RuntimeError handler reports {levels}, expected exactly ['ERROR']"
    )


def test_the_dispatcher_strips_blenders_doubled_error_prefix():
    """Blender prepends "Error: " to the RuntimeError text; re-reporting it
    verbatim shows the user that prefix twice."""
    source = DISPATCHER_PY.read_text()
    assert '"Error: "' in source, (
        "prompt_generate_ops.py no longer de-prefixes Blender's 'Error: '"
    )
    handler = _dispatcher_handler()
    body = ast.dump(ast.Module(body=handler.body, type_ignores=[]))
    assert "startswith" in body and "Error: " in body, (
        "the 'Error: ' prefix is not stripped inside the RuntimeError handler"
    )
