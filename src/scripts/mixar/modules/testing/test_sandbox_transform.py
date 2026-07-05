# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for space_mixie_chat.core.sandbox_transform module.

Tests the crash-safety AST transform that snapshots live-collection ``for``
loops (``for x in <coll>.all_objects:`` -> ``for x in list(...):``) so a
mutation inside the loop cannot free the RNA array the C iterator walks — the
native ``Collection_all_objects_next`` segfault that no ``try/except`` can catch.
"""

# Install bpy mock before any mixar imports
import sys, os
_test_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.abspath(os.path.join(_test_dir, "..", "..", ".."))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
try:
    import bpy
except ImportError:
    import importlib.util
    _mock_spec = importlib.util.spec_from_file_location(
        "mock_bpy", os.path.join(_test_dir, "mock_bpy.py"))
    _mock_mod = importlib.util.module_from_spec(_mock_spec)
    _mock_spec.loader.exec_module(_mock_mod)

import ast
import types
import unittest


class _LiveCollection:
    """Stand-in for a bpy RNA collection.

    Mutating it *while it is being iterated* raises RuntimeError — the pure-Python
    analogue of Blender's native segfault when the C iterator's backing array is
    freed mid-walk. Iterating a ``list(...)`` snapshot instead never sets the
    iterating flag during the body, so the mutation is safe.
    """

    def __init__(self, items):
        self._items = list(items)
        self._iterating = False

    def __iter__(self):
        self._iterating = True
        try:
            for it in list(self._items):
                yield it
        finally:
            self._iterating = False

    def remove(self, item):
        if self._iterating:
            raise RuntimeError(
                "collection mutated during live iteration "
                "(this is a native segfault in real Blender)"
            )
        self._items.remove(item)


class TestSnapshotSource(unittest.TestCase):
    """String-level assertions on the rewritten source."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.space_mixie_chat.core.sandbox_transform import (
            snapshot_collection_iterations_source,
        )
        cls.rewrite = staticmethod(snapshot_collection_iterations_source)

    # -- iterables that MUST be wrapped ------------------------------------

    def test_wraps_bpy_data_objects(self):
        out = self.rewrite("for obj in bpy.data.objects:\n    pass")
        self.assertIn("list(bpy.data.objects)", out)

    def test_wraps_all_objects(self):
        out = self.rewrite(
            "for o in bpy.context.scene.collection.all_objects:\n    pass"
        )
        self.assertIn("list(bpy.context.scene.collection.all_objects)", out)

    def test_wraps_collection_objects(self):
        out = self.rewrite("for o in coll.objects:\n    coll.objects.unlink(o)")
        self.assertIn("list(coll.objects)", out)

    def test_wraps_nested_loops(self):
        src = (
            "for c in bpy.data.collections:\n"
            "    for o in c.all_objects:\n"
            "        pass"
        )
        out = self.rewrite(src)
        # Inner loop over a live collection is wrapped; the outer over
        # `.collections` is not in scope for this transform.
        self.assertIn("list(c.all_objects)", out)

    # -- iterables that must be LEFT ALONE ---------------------------------

    def test_does_not_double_wrap(self):
        out = self.rewrite("for o in list(bpy.data.objects):\n    pass")
        self.assertEqual(out.count("list("), 1)

    def test_leaves_selected_objects(self):
        # selected_objects already returns a fresh Python list — snapshot-safe.
        out = self.rewrite("for o in bpy.context.selected_objects:\n    pass")
        self.assertNotIn("list(", out)

    def test_leaves_range(self):
        out = self.rewrite("for i in range(10):\n    pass")
        self.assertNotIn("list(", out)

    def test_leaves_plain_name(self):
        out = self.rewrite("items = []\nfor o in items:\n    pass")
        self.assertNotIn("list(", out)

    def test_leaves_values_call(self):
        # `.objects.values()` is already a list; the iterable is a Call, not an
        # Attribute, so it is not rewritten.
        out = self.rewrite("for o in coll.objects.values():\n    pass")
        self.assertNotIn("list(coll.objects.values", out)

    def test_syntax_error_returns_none(self):
        self.assertIsNone(self.rewrite("for x in :\n"))

    # -- variable-bound-then-immediately-iterated (adjacent) is covered -----

    def test_wraps_adjacent_bound_collection(self):
        src = (
            "objs = bpy.context.scene.collection.all_objects\n"
            "for obj in objs:\n"
            "    bpy.data.objects.remove(obj)"
        )
        out = self.rewrite(src)
        # The binding is left as a live collection; the LOOP iterable is wrapped.
        self.assertIn("for obj in list(objs):", out)
        self.assertIn("objs = bpy.context.scene.collection.all_objects", out)

    def test_adjacent_binding_leaves_other_uses_intact(self):
        # Wrapping the loop (not the binding) means `objs.new(...)` still works —
        # `list(...)` has no `.new`, so rewriting the binding would break it.
        src = (
            "objs = bpy.data.objects\n"
            "for o in objs:\n"
            "    pass\n"
            "objs.new('X', None)"
        )
        out = self.rewrite(src)
        self.assertIn("for o in list(objs):", out)
        self.assertIn("objs.new('X', None)", out)

    def test_non_adjacent_bound_collection_documented_gap(self):
        # KNOWN LIMITATION: a statement between the binding and the loop means the
        # syntactic adjacency rule does not fire. Documented, not a guarantee.
        src = (
            "objs = bpy.data.objects\n"
            "print(len(objs))\n"
            "for o in objs:\n"
            "    pass"
        )
        out = self.rewrite(src)
        self.assertNotIn("list(", out)


class TestSnapshotSemantics(unittest.TestCase):
    """Functional proof: the transform neutralises mutation-during-iteration."""

    def setUp(self):
        from mixar.modules.space_mixie_chat.core.sandbox_transform import (
            snapshot_collection_iterations,
        )
        self.transform = snapshot_collection_iterations

    def _run(self, script, apply_transform):
        scene = types.SimpleNamespace(objects=_LiveCollection(["a", "b", "c"]))
        ns = {"scene": scene, "list": list}
        tree = ast.parse(script, mode="exec")
        if apply_transform:
            tree = self.transform(tree)
        exec(compile(tree, "<test>", "exec"), ns)  # noqa: S102
        return scene, ns

    _MUTATING_SCRIPT = (
        "removed = []\n"
        "for obj in scene.objects:\n"
        "    removed.append(obj)\n"
        "    scene.objects.remove(obj)\n"
    )

    def test_untransformed_script_crashes(self):
        # Sanity check: without the transform, the crash pattern raises
        # (models the real segfault).
        with self.assertRaises(RuntimeError):
            self._run(self._MUTATING_SCRIPT, apply_transform=False)

    def test_transformed_script_is_safe(self):
        # With the transform, the loop iterates a snapshot and the same
        # mutation is safe — all three objects removed, no error.
        scene, ns = self._run(self._MUTATING_SCRIPT, apply_transform=True)
        self.assertEqual(ns["removed"], ["a", "b", "c"])
        self.assertEqual(scene.objects._items, [])

    _ADJACENT_MUTATING_SCRIPT = (
        "removed = []\n"
        "objs = scene.objects\n"
        "for obj in objs:\n"
        "    removed.append(obj)\n"
        "    scene.objects.remove(obj)\n"
    )

    def test_adjacent_bound_untransformed_crashes(self):
        with self.assertRaises(RuntimeError):
            self._run(self._ADJACENT_MUTATING_SCRIPT, apply_transform=False)

    def test_adjacent_bound_transformed_is_safe(self):
        scene, ns = self._run(self._ADJACENT_MUTATING_SCRIPT, apply_transform=True)
        self.assertEqual(ns["removed"], ["a", "b", "c"])
        self.assertEqual(scene.objects._items, [])

    def test_read_only_iteration_unchanged_behaviour(self):
        script = (
            "names = []\n"
            "for obj in scene.objects:\n"
            "    names.append(obj)\n"
        )
        _, ns = self._run(script, apply_transform=True)
        self.assertEqual(ns["names"], ["a", "b", "c"])


if __name__ == "__main__":
    unittest.main()
