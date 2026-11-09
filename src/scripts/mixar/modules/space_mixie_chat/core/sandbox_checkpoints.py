# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Compile stop checks into the model's own code (#1911).

``common/agent_execution/script_time_limit.py`` stops a raw agent script once
the backend has stopped waiting for it. The stop can only happen at a check
this transform places in the model's code, so it is an ordinary exception
raised by a line of that code:

- before each statement outside loops and functions (after a docstring and
  ``from __future__`` imports);
- at the start of each loop turn and each call of a function the model
  defined, recursion included (inside those, only the body's head is
  checked, so a tight loop pays one check per turn);
- at the start of each lambda call (``sorted(key=lambda ...)`` runs it from C);
- as the first filter of each comprehension clause.

A check is ``if _mixar_tl_hit: _mixar_tl_stop()``: one global read while the
script is within its limit. A ``finally`` body in the run is checked like any
block but holds the stop while it runs (``script_time_limit.HARD_GRACE_S`` at
most), so cleanup that calls the model's own functions completes too. A loop
turn or function call that makes several long native calls in a row is stopped
at its next check, after them.

Only the model's code is instrumented. A backend that wraps it in scaffolding
marks the model's part with ``MODEL_RUN_BEGIN`` / ``MODEL_RUN_END`` comment
lines; statements outside them are left exactly as sent. That covers the
workspace data view before the run and the modifier-cost guard after it: the
guard is the run's ``finally``, below ``MODEL_RUN_END``, so it gets the hold but
no checks and runs whole however late the stop comes. A scaffolded script from
a backend that predates the markers (``SCAFFOLD_MARK``, no run markers) is not
instrumented at all; a plain script is instrumented whole.
"""

from __future__ import annotations

import ast
from typing import Optional

from mixar.config.logging_config import get_logger
from mixar.modules.common.agent_execution.script_time_limit import (
    HIT_NAME,
    HOLD_NAME,
    RELEASE_NAME,
    STOP_NAME,
)

logger = get_logger(__name__)

# Comment lines (column 0) the backend puts around the model's code inside a
# scaffolded script (mixar-backend ``workspace_rewrite.MODEL_RUN_BEGIN``).
MODEL_RUN_BEGIN = "# >>> mixar model run"
MODEL_RUN_END = "# <<< mixar model run"
# First line of the model-code comment block every scaffolded script starts
# with, from the first backend that scaffolded (``MODEL_CODE_BEGIN``).
SCAFFOLD_MARK = "# >>> model code (as written)"

_NO_SPAN = None


def model_span(source: str) -> Optional[tuple[float, float]]:
    """Exclusive (first, last) line bounds of the model's code, or None.

    None means "instrument nothing": a scaffolded script whose model part is
    not marked, or markers that do not pair up.
    """
    lines = source.split("\n")
    begins = [i + 1 for i, line in enumerate(lines) if line.rstrip() == MODEL_RUN_BEGIN]
    ends = [i + 1 for i, line in enumerate(lines) if line.rstrip() == MODEL_RUN_END]
    if begins or ends:
        if len(begins) != 1 or len(ends) != 1 or ends[0] <= begins[0]:
            logger.warning("Agent script run markers do not pair up (begin lines %s, end lines %s): "
                           "it runs without stop checks", begins, ends)
            return _NO_SPAN
        return float(begins[0]), float(ends[0])
    if any(line.rstrip() == SCAFFOLD_MARK for line in lines):
        return _NO_SPAN
    return 0.0, float("inf")


def _load(name: str) -> ast.Name:
    return ast.Name(id=name, ctx=ast.Load())


def _call(name: str) -> ast.Call:
    return ast.Call(func=_load(name), args=[], keywords=[])


def _hit_and_stop() -> ast.BoolOp:
    """``_mixar_tl_hit and _mixar_tl_stop()``: falsy unless it raises."""
    return ast.BoolOp(op=ast.And(), values=[_load(HIT_NAME), _call(STOP_NAME)])


def _is_docstring(stmt: ast.stmt) -> bool:
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str))


def _is_future_import(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.ImportFrom) and stmt.module == "__future__"


_DOCSTRING_OWNERS = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_TRY_NODES = (ast.Try, ast.TryStar) if hasattr(ast, "TryStar") else (ast.Try,)


_HEAD_ONLY = (ast.For, ast.AsyncFor, ast.While, ast.FunctionDef, ast.AsyncFunctionDef)
# Annotations are left as written: under ``from __future__ import annotations``
# they become strings the script can read back (``__annotations__``).
_ANNOTATION_FIELDS = frozenset({"annotation", "returns"})


class _Checkpoints(ast.NodeTransformer):
    def __init__(self, span: tuple[float, float]):
        self.first, self.last = span
        self.added = 0
        # Inside a loop or function body: only each body's head is checked.
        self.hot = False

    def in_span(self, stmt: ast.stmt) -> bool:
        line = getattr(stmt, "lineno", None)
        return line is not None and self.first < line < self.last

    def check(self, at: ast.stmt) -> ast.If:
        self.added += 1
        return ast.copy_location(ast.If(
            test=_load(HIT_NAME), body=[ast.Expr(value=_call(STOP_NAME))], orelse=[],
        ), at)

    def block(self, stmts: list, owner: ast.AST, mode: str) -> list:
        """Statements in span, instrumented; ``mode`` "each" checks before
        every one, "head" before the first, "none" adds no check here."""
        out = []
        checked = False
        for index, stmt in enumerate(stmts):
            if not self.in_span(stmt):
                out.append(stmt)
                continue
            leading = (index == 0 and isinstance(owner, _DOCSTRING_OWNERS)
                       and _is_docstring(stmt)) or _is_future_import(stmt)
            if not leading and (mode == "each" or (mode == "head" and not checked)):
                out.append(self.check(stmt))
                checked = True
            out.append(self.visit(stmt))
        return out

    def held(self, stmts: list) -> list:
        """A (checked) ``finally`` body, holding the stop until it ends."""
        if not stmts:
            return stmts
        hold = ast.copy_location(ast.Expr(value=_call(HOLD_NAME)), stmts[0])
        release = ast.copy_location(ast.Expr(value=_call(RELEASE_NAME)), stmts[-1])
        inner = ast.copy_location(
            ast.Try(body=stmts, handlers=[], orelse=[], finalbody=[release]), stmts[0])
        return [hold, inner]

    def generic_visit(self, node: ast.AST) -> ast.AST:
        for field, value in ast.iter_fields(node):
            if field in _ANNOTATION_FIELDS:
                continue
            if field == "finalbody" and isinstance(node, _TRY_NODES):
                node.finalbody = self.held(self.block(value, node, "none" if self.hot else "each"))
            elif isinstance(value, list) and value and isinstance(value[0], ast.stmt):
                head = field == "body" and isinstance(node, _HEAD_ONLY)
                hot = self.hot
                self.hot = hot or head
                setattr(node, field, self.block(
                    value, node, "head" if head else "none" if hot else "each"))
                self.hot = hot
            elif isinstance(value, list):
                setattr(node, field, [self.visit(v) if isinstance(v, ast.AST) else v
                                      for v in value])
            elif isinstance(value, ast.AST):
                setattr(node, field, self.visit(value))
        return node

    def visit_Lambda(self, node: ast.Lambda) -> ast.Lambda:
        self.generic_visit(node)
        self.added += 1
        node.body = ast.copy_location(
            ast.BoolOp(op=ast.Or(), values=[_hit_and_stop(), node.body]), node.body)
        return node

    def visit_comprehension(self, node: ast.comprehension) -> ast.comprehension:
        self.generic_visit(node)
        self.added += 1
        node.ifs.insert(0, ast.UnaryOp(op=ast.Not(), operand=_hit_and_stop()))
        return node


def add_stop_checkpoints(tree: ast.Module, source: str) -> int:
    """Instrument ``tree`` (parsed from ``source``) in place; return the check count."""
    span = model_span(source)
    if span is _NO_SPAN:
        return 0
    transformer = _Checkpoints(span)
    tree.body = transformer.block(tree.body, tree, "each")
    ast.fix_missing_locations(tree)
    return transformer.added
