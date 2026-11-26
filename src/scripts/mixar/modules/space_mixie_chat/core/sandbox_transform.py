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

    objs = bpy.data.objects
    for i, obj in enumerate(objs):
        if i + 1 < len(objs):
            objs.remove(objs[i + 1])  # the item right after the current one

``bpy.data.objects`` / ``collection.objects`` are live RNA collections that the
C iterator walks link by link. Python's ``for`` fetches the next element before
the body runs, so the iterator holds a raw pointer to exactly one link: the one
right after the current item. Unlinking any other item updates its neighbours,
so removing the current item or one further ahead is survivable; removing the
item right after the current one (``.remove``, ``bpy.ops.object.delete`` or
``join`` on a selection, ...) frees the link the iterator already holds, and
the next iteration reads freed memory — a native segfault that no
``try/except`` in the executor can catch, taking the user's unsaved work with
it.

The same mechanism is not specific to objects: any live RNA collection whose
elements the loop body removes (``node_tree.nodes``/``.links`` clears in
material scripts, ``bpy.data.materials``/``.images`` cleanup sweeps,
``bpy.data.scenes``/``.collections`` lane teardown, modifier/constraint stack
removal) reads freed memory the same way. ``_LIVE_COLLECTION_ATTRS`` below
lists the covered attributes. ``Collection.all_objects`` is worse: it walks a
Base cache that any link, unlink or delete frees whole, so any membership
change inside the loop is fatal; it is iterated as a native snapshot
(MIXAR-1978, ``python/intern/bpy_rna.cc``), so the transform is defence in
depth there.

Wrapping the iterable in a list snapshot drains the collection into a plain
Python list up front, so the loop walks Python references instead of the live C
array. Membership changes no longer invalidate the iterator. This is
body-agnostic: it fixes the crash no matter *how* the loop mutates, without
having to enumerate every mutating call. A snapshot of ``bpy.data.objects`` is
semantically identical for the common (read-only) case and matches the author's
intent in the mutating case.

The injected call is ``_mixar_snapshot(EXPR)`` (``SNAPSHOT_FUNC_NAME``), not
``list(EXPR)``: a script may bind ``list`` itself (a module global, a parameter
or a local), which would turn every rewritten loop into a ``TypeError``. The
executor binds the reserved global to :func:`snapshot_iterable` in the script's
namespace. It drains through ``iter()`` only: ``list(x)`` would also call
``x.__len__`` as a length hint, and the backend's scoped ``__ws_data``
collection views run a full scope scan in both ``__len__`` and ``__iter__``.

The snapshot holds Python wrappers, which do not keep their elements alive.
Only IDs are invalidated on deletion (``lib_id_delete.cc`` clears the ID's
``py_instance``), so reaching a deleted ID through the snapshot raises
``ReferenceError``. Release builds do not define ``WITH_PYTHON_SAFETY``, so a
non-ID struct (node, link, modifier, constraint, vertex group, UV layer, edit
bone) freed indirectly (by an operator, a ``.clear()``, or ``.remove()`` called
with another wrapper of it) leaves its snapshot wrapper dangling, and reaching
it is still a native use-after-free.

Comprehension clauses (including generator expressions) receive the same
snapshot before their filters or elements execute. A generator's outer
iterable is snapshotted when the generator is created; inner clauses snapshot
when entered. Async iteration is excluded.

Coverage — this handles the dominant iteration shapes, all purely
syntactically (no dataflow analysis, which aliasing/reassignment would make
unreliable):

    for obj in bpy.data.objects: ...              # inline attribute iterable
    for i, obj in enumerate(coll.objects): ...    # live argument of a lazy builtin
    objs = coll.objects
    for obj in objs: ...                          # bound then *immediately* iterated

The lazy builtins are plain-name ``enumerate``, ``zip``, ``filter`` and
``map``: each positional argument that is a live attribute is snapshotted
(``enumerate(_mixar_snapshot(coll.objects))``); keyword arguments and other
callables are left alone (``sorted``/``list`` already drain their argument).
The adjacent-binding rule still needs a bare ``for x in NAME:``.

It does NOT catch a live collection bound to a variable and iterated later with
other statements in between (``objs = coll.objects; print(...); for o in
objs:``) — removing a not-yet-visited item there can still segfault; only
``Collection.all_objects`` is safe in that form, through the native snapshot.
The backend prompt guidance (``execute_bpy_script`` docstring) steers the model
away from those forms; this transform is the in-plugin safety net for the
common shapes.
"""

import ast
from typing import Optional

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Reserved global the injected snapshot call names. The executor binds it to
# ``snapshot_iterable`` in every script namespace this transform runs on.
SNAPSHOT_FUNC_NAME = "_mixar_snapshot"


def snapshot_iterable(iterable):
    """Drain *iterable* into a list via ``iter()`` alone.

    ``list(iterable)`` asks the object for ``__len__`` as a length hint before
    iterating; on the backend's scoped ``__ws_data`` views that is a second full
    scope scan. ``iter()`` returns a native bpy collection's own iterator (or
    the view's list iterator), whose length hint costs nothing.
    """
    return list(iter(iterable))


# Attribute names that resolve to a LIVE bpy RNA collection whose backing array
# is freed on membership change. Iterating one of these directly (not via
# a list snapshot) and mutating inside the loop segfaults Blender.
#
# Beyond the original ``.objects``/``.all_objects`` crash, the same
# mechanism (C iterator holding a pointer into a ListBase/Main-backed array
# freed by ``.remove()``/``.unlink()``/an operator inside the body) applies to
# the collections agent texturing and scene-lane scripts routinely clear in a
# loop: ``node_tree.nodes``/``.links`` ("clear the node tree"), ``bpy.data
# .materials``/``.images``/``.meshes`` (cleanup sweeps), ``bpy.data
# .collections``/``.scenes``/``collection.children`` (lane teardown), and the
# per-object stacks (``modifiers``, ``constraints``, ``vertex_groups``,
# ``uv_layers``, ``edit_bones``).
#
# Deliberate exclusions:
# - ``selected_objects`` — returns a fresh Python list per access, already safe.
# - High-cardinality mesh data (``vertices``, ``edges``, ``loops``,
#   ``polygons``) — not element-removable mid-loop through these handles, and a
#   list snapshot of a million-element array per loop would be a real
#   performance regression on exactly the heavy scripts this guards.
_LIVE_COLLECTION_ATTRS = frozenset({
    # object membership
    "objects", "all_objects", "children",
    # bpy.data ID collections agent scripts sweep-clean
    "materials", "meshes", "images", "collections", "scenes", "node_groups",
    # node-tree editing ("clear all nodes/links" idiom in material scripts)
    "nodes", "links",
    # per-object / per-mesh stacks removed element-wise in loops
    "modifiers", "constraints", "vertex_groups", "uv_layers", "edit_bones",
})


def _is_live_collection(expr: ast.expr) -> bool:
    """True for ``<anything>.<attr>`` with ``attr`` in ``_LIVE_COLLECTION_ATTRS``."""
    return isinstance(expr, ast.Attribute) and expr.attr in _LIVE_COLLECTION_ATTRS


# Builtins that iterate their positional arguments lazily, in step with the
# loop: ``for i, o in enumerate(coll.objects):`` still walks the live native
# iterator while the body runs. ``sorted``/``list``/``tuple`` drain their
# argument up front and need no snapshot.
_LAZY_ITERATION_WRAPPERS = frozenset({"enumerate", "zip", "filter", "map"})


def _is_lazy_iteration_wrapper(expr: ast.expr) -> bool:
    """True for a call to a plain-name ``enumerate``/``zip``/``filter``/``map``."""
    return (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Name)
        and expr.func.id in _LAZY_ITERATION_WRAPPERS
    )


class _SnapshotForIterables(ast.NodeTransformer):
    """Wrap live-collection iterables of ``for`` loops and comprehensions.

    Rewrites ``for x in EXPR:`` and every synchronous comprehension clause
    (list, set, dict, generator) to iterate ``_mixar_snapshot(EXPR)`` when
    ``EXPR`` is an attribute in ``_LIVE_COLLECTION_ATTRS`` (see
    :func:`_is_live_collection`). When ``EXPR`` is a call to plain-name
    ``enumerate``/``zip``/``filter``/``map``, each positional argument that is
    such an attribute is wrapped instead. Iterables that are already wrapped
    (by the transform or the author's own ``list(...)``), ``.values()`` calls,
    plain names, keyword arguments, other callables, or anything else are left
    untouched.
    """

    def __init__(self) -> None:
        self.rewrites = 0

    def _snapshot(self, node: ast.For | ast.comprehension) -> None:
        iter_node = node.iter
        if _is_live_collection(iter_node):
            # Replace `EXPR` with `_mixar_snapshot(EXPR)` so the collection is
            # drained into a Python list before the loop body can mutate it.
            node.iter = _wrap_in_snapshot(iter_node)
            self.rewrites += 1
        elif _is_lazy_iteration_wrapper(iter_node):
            # `enumerate(EXPR)` etc. pull from EXPR as the loop advances, so
            # snapshot the live arguments themselves. An argument already
            # wrapped is a Call, not an Attribute, which keeps this idempotent.
            for index, arg in enumerate(iter_node.args):
                if _is_live_collection(arg):
                    iter_node.args[index] = _wrap_in_snapshot(arg)
                    self.rewrites += 1

    def visit_For(self, node: ast.For) -> ast.AST:
        self._snapshot(node)
        self.generic_visit(node)
        return node

    def visit_comprehension(self, node: ast.comprehension) -> ast.AST:
        # Filters and element expressions may mutate the collection too.
        if not node.is_async:
            self._snapshot(node)
        self.generic_visit(node)
        return node


def _wrap_in_snapshot(expr: ast.expr) -> ast.Call:
    """Return ``_mixar_snapshot(expr)`` as an AST Call at ``expr``'s location.

    Copying the iterable's span (including end positions) keeps tracebacks and
    crash reports' ``<agent_script>:N`` on the iterable's own line instead of
    a location inherited from an enclosing multi-line statement.
    """
    name = ast.Name(id=SNAPSHOT_FUNC_NAME, ctx=ast.Load())
    func = ast.copy_location(name, expr)
    return ast.copy_location(ast.Call(func=func, args=[expr], keywords=[]), expr)


# Statement-list fields on AST nodes that form an execution block.
_BLOCK_FIELDS = ("body", "orelse", "finalbody")


def _snapshot_adjacent_bindings(tree: ast.AST) -> int:
    """Snapshot the ``NAME = <live coll>; for x in NAME:`` idiom.

    Handles the case the inline transform misses — a live collection bound to a
    variable and then iterated on the *immediately following* statement. Purely
    syntactic (adjacency only, no dataflow): fires only when the very next
    statement is a ``for`` over that exact name, and rewrites the *loop's*
    iterable (``for x in _mixar_snapshot(NAME):``) rather than the binding —
    so any other use of ``NAME`` (e.g. ``NAME.new(...)``) is left untouched and
    cannot break.
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
                    and _is_live_collection(a.value)
                    and isinstance(b, ast.For)
                    and isinstance(b.iter, ast.Name)
                    and b.iter.id == a.targets[0].id
                ):
                    b.iter = _wrap_in_snapshot(b.iter)
                    rewrites += 1
    return rewrites


def snapshot_collection_iterations(tree: ast.Module) -> ast.Module:
    """Make loops and comprehensions over live collections iterate a snapshot.

    Covers inline ``for``/comprehension iterables and the adjacent
    ``NAME = <live coll>; for x in NAME:`` binding; see the module docstring.

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
            "Snapshotted %d live-collection loop(s) for crash safety",
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
