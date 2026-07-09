# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
AST transforms that make agent-generated bpy scripts crash-safe.

Unlike ``sandbox_validator`` (which *rejects* unsafe scripts), these transforms
silently rewrite a script into an equivalent-but-safe form before compilation.

The one transform here — :func:`snapshot_collection_iterations` — defends against
a hard, uncatchable Blender crash: mutating a live ``bpy`` collection while
iterating it.

    for obj in bpy.context.scene.collection.all_objects:
        bpy.data.objects.remove(obj)          # <-- frees the array the C-level
                                              #     iterator is walking -> segfault

``collection.all_objects`` / ``collection.objects`` / ``bpy.data.objects`` are
live RNA collections backed by a C ``ListBase`` cache. Adding or removing an
object (``.remove``/``.link``/``.unlink``, ``bpy.ops.object.delete``/``join``,
any ``*_add`` operator, ...) invalidates and frees that cache. Because the
Python ``for`` loop holds a raw pointer into it, the *next* iteration reads freed
memory and Blender dies with a native segfault in ``Collection_all_objects_next``
— which no ``try/except`` in the executor can catch, taking the user's unsaved
work with it.

Wrapping the iterable in ``list(...)`` drains the collection into a plain Python
list up front, so the loop walks Python references instead of the live C array.
Any mutation inside the body is then safe. This is body-agnostic: it fixes the
crash no matter *how* the loop mutates, without having to enumerate every
mutating call. ``list(coll.all_objects)`` is semantically identical for the
common (read-only) case and matches the author's intent in the mutating case.

Coverage — this handles the two dominant idioms, both purely syntactically (no
dataflow analysis, which aliasing/reassignment would make unreliable):

    for obj in bpy.data.objects: ...              # inline attribute iterable
    objs = coll.all_objects
    for obj in objs: ...                          # bound then *immediately* iterated

It does NOT catch a live collection bound to a variable and iterated later with
other statements in between (``objs = coll.all_objects; print(...); for o in
objs:``) — that still segfaults if mutated. The backend prompt guidance
(``execute_bpy_script`` docstring) steers the model away from those forms; this
transform is the in-plugin safety net for the common shapes.
"""

import ast
from typing import Optional

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


# Attribute names that resolve to a LIVE bpy RNA collection whose backing array
# is freed on membership change. Iterating one of these directly (not via
# ``list(...)``) and mutating inside the loop segfaults Blender.
#
# Intentionally NARROW: ``selected_objects`` is excluded — it returns a fresh
# Python list on each access, so it is already snapshot-safe. Extend this set if
# other live collections (e.g. ``children`` for collection hierarchies) prove to
# hit the same crash.
_LIVE_COLLECTION_ATTRS = frozenset({"objects", "all_objects"})


class _SnapshotForIterables(ast.NodeTransformer):
    """Wrap ``for x in <live collection>:`` iterables in ``list(...)``.

    Only rewrites when the iterable is an attribute access whose final attribute
    is a known live collection (``.objects`` / ``.all_objects``). Iterables that
    are already ``list(...)``-wrapped, comprehension calls, ``.values()`` calls,
    plain names, or anything else are left untouched.
    """

    def __init__(self) -> None:
        self.rewrites = 0

    def _snapshot(self, node: ast.For) -> None:
        iter_node = node.iter
        if not isinstance(iter_node, ast.Attribute):
            return
        if iter_node.attr not in _LIVE_COLLECTION_ATTRS:
            return
        # Replace `EXPR` with `list(EXPR)` so the collection is drained into a
        # Python list before the loop body can mutate the live collection.
        node.iter = _wrap_in_list(iter_node)
        self.rewrites += 1

    def visit_For(self, node: ast.For) -> ast.AST:
        self._snapshot(node)
        self.generic_visit(node)
        return node


def _wrap_in_list(expr: ast.expr) -> ast.Call:
    """Return ``list(expr)`` as an AST Call node."""
    return ast.Call(
        func=ast.Name(id="list", ctx=ast.Load()),
        args=[expr],
        keywords=[],
    )


# Statement-list fields on AST nodes that form an execution block.
_BLOCK_FIELDS = ("body", "orelse", "finalbody")


def _snapshot_adjacent_bindings(tree: ast.AST) -> int:
    """Snapshot the ``NAME = <live coll>; for x in NAME:`` idiom.

    Handles the case the inline transform misses — a live collection bound to a
    variable and then iterated on the *immediately following* statement. Purely
    syntactic (adjacency only, no dataflow): fires only when the very next
    statement is a ``for`` over that exact name, and rewrites the *loop's*
    iterable (``for x in list(NAME):``) rather than the binding — so any other
    use of ``NAME`` (e.g. ``NAME.new(...)``) is left untouched and cannot break.
    """
    rewrites = 0
    for node in ast.walk(tree):
        for field in _BLOCK_FIELDS:
            stmts = getattr(node, field, None)
            if not isinstance(stmts, list):
                continue
            for a, b in zip(stmts, stmts[1:]):
                if (
                    isinstance(a, ast.Assign)
                    and len(a.targets) == 1
                    and isinstance(a.targets[0], ast.Name)
                    and isinstance(a.value, ast.Attribute)
                    and a.value.attr in _LIVE_COLLECTION_ATTRS
                    and isinstance(b, ast.For)
                    and isinstance(b.iter, ast.Name)
                    and b.iter.id == a.targets[0].id
                ):
                    b.iter = _wrap_in_list(b.iter)
                    rewrites += 1
    return rewrites


def snapshot_collection_iterations(tree: ast.Module) -> ast.Module:
    """Rewrite live-collection ``for`` loops to iterate a ``list(...)`` snapshot.

    Mutates ``tree`` in place and returns it (with locations fixed so the result
    is ready to ``compile``).

    Args:
        tree: Parsed AST module of an agent script.

    Returns:
        The same tree, with unsafe live-collection iterations made crash-safe.
    """
    transformer = _SnapshotForIterables()
    transformer.visit(tree)
    rewrites = transformer.rewrites + _snapshot_adjacent_bindings(tree)
    if rewrites:
        ast.fix_missing_locations(tree)
        logger.debug(
            "Snapshotted %d live-collection loop(s) with list() for crash safety",
            rewrites,
        )
    return tree


def snapshot_collection_iterations_source(script: str) -> Optional[str]:
    """Convenience wrapper: transform a script string, return rewritten source.

    Returns ``None`` if the script cannot be parsed (the caller should let the
    normal compile step surface the syntax error). Primarily for tests and
    debugging — the executor works on the AST directly to avoid a re-parse.
    """
    try:
        tree = ast.parse(script, filename="<agent_script>", mode="exec")
    except SyntaxError:
        return None
    snapshot_collection_iterations(tree)
    return ast.unparse(tree)
