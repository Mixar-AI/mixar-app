# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for space_mixie_chat.core.sandbox_transform module.

Tests the crash-safety AST transform that snapshots live-collection iterables
of ``for`` loops and comprehensions (``for x in <coll>.all_objects:`` ->
``for x in _mixar_snapshot(...):``, a list snapshot under a reserved name so a
script that binds ``list`` still works) so a mutation inside the loop cannot
free the RNA storage the C iterator walks — the native
``Collection_all_objects_next`` segfault that no ``try/except`` can catch. Also
pins that the injected call keeps the iterable's source location.
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
    freed mid-walk. Iterating a list snapshot instead never sets the
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
        self.assertIn("_mixar_snapshot(bpy.data.objects)", out)

    def test_wraps_all_objects(self):
        out = self.rewrite(
            "for o in bpy.context.scene.collection.all_objects:\n    pass"
        )
        self.assertIn("_mixar_snapshot(bpy.context.scene.collection.all_objects)", out)

    def test_wraps_collection_objects(self):
        out = self.rewrite("for o in coll.objects:\n    coll.objects.unlink(o)")
        self.assertIn("_mixar_snapshot(coll.objects)", out)

    def test_wraps_nested_loops(self):
        src = (
            "for c in bpy.data.collections:\n"
            "    for o in c.all_objects:\n"
            "        pass"
        )
        out = self.rewrite(src)
        # Both levels are live collections — both get snapshotted.
        self.assertIn("_mixar_snapshot(bpy.data.collections)", out)
        self.assertIn("_mixar_snapshot(c.all_objects)", out)

    def test_wraps_node_tree_clear_idiom(self):
        # The classic "clear the node tree" loop in material scripts — same
        # freed-ListBase segfault class as the object-collection crash.
        src = (
            "nodes = mat.node_tree.nodes\n"
            "for n in mat.node_tree.nodes:\n"
            "    nodes.remove(n)"
        )
        out = self.rewrite(src)
        self.assertIn("_mixar_snapshot(mat.node_tree.nodes)", out)

    def test_wraps_links_clear(self):
        out = self.rewrite(
            "for l in tree.links:\n    tree.links.remove(l)"
        )
        self.assertIn("_mixar_snapshot(tree.links)", out)

    def test_wraps_data_materials_sweep(self):
        out = self.rewrite(
            "for m in bpy.data.materials:\n    bpy.data.materials.remove(m)"
        )
        self.assertIn("_mixar_snapshot(bpy.data.materials)", out)

    def test_wraps_scene_teardown(self):
        out = self.rewrite(
            "for s in bpy.data.scenes:\n    bpy.data.scenes.remove(s)"
        )
        self.assertIn("_mixar_snapshot(bpy.data.scenes)", out)

    def test_wraps_collection_children(self):
        out = self.rewrite(
            "for c in parent.children:\n    parent.children.unlink(c)"
        )
        self.assertIn("_mixar_snapshot(parent.children)", out)

    def test_wraps_modifier_stack_removal(self):
        out = self.rewrite(
            "for md in obj.modifiers:\n    obj.modifiers.remove(md)"
        )
        self.assertIn("_mixar_snapshot(obj.modifiers)", out)

    def test_wraps_live_arguments_of_lazy_builtins(self):
        for source, expected in (
            ("for i, o in enumerate(coll.objects):\n    pass",
             "enumerate(_mixar_snapshot(coll.objects))"),
            ("for a, b in zip(tree.nodes, tree.links):\n    pass",
             "zip(_mixar_snapshot(tree.nodes), _mixar_snapshot(tree.links))"),
            ("for o in filter(None, scene.objects):\n    pass",
             "filter(None, _mixar_snapshot(scene.objects))"),
            ("for n in map(str, bpy.data.materials):\n    pass",
             "map(str, _mixar_snapshot(bpy.data.materials))"),
            ("[o for i, o in enumerate(coll.objects)]",
             "enumerate(_mixar_snapshot(coll.objects))"),
            ("{a: b for a, b in zip(names, scene.objects)}",
             "zip(names, _mixar_snapshot(scene.objects))"),
            ("[o for o in filter(None, scene.objects)]",
             "filter(None, _mixar_snapshot(scene.objects))"),
            ("(n for n in map(str, obj.modifiers))",
             "map(str, _mixar_snapshot(obj.modifiers))"),
        ):
            with self.subTest(source=source):
                out = self.rewrite(source)
                self.assertIn(expected, out)
                self.assertEqual(out, self.rewrite(out))

    # -- iterables that must be LEFT ALONE ---------------------------------

    def test_leaves_lazy_builtin_without_live_argument(self):
        for source in (
            "for i, v in enumerate(mesh.vertices):\n    pass",
            "for o in sorted(coll.objects):\n    pass",
            "[o for o in sorted(coll.objects, key=f)]",
            "for o in my.enumerate(coll.objects):\n    pass",
            "for p in zip(names, strict=coll.objects):\n    pass",
        ):
            with self.subTest(source=source):
                self.assertNotIn("_mixar_snapshot", self.rewrite(source))

    def test_does_not_double_wrap(self):
        out = self.rewrite("for o in list(bpy.data.objects):\n    pass")
        self.assertEqual(out.count("list("), 1)
        self.assertNotIn("_mixar_snapshot", out)

    def test_leaves_selected_objects(self):
        # selected_objects already returns a fresh Python list — snapshot-safe.
        out = self.rewrite("for o in bpy.context.selected_objects:\n    pass")
        self.assertNotIn("_mixar_snapshot", out)

    def test_leaves_high_cardinality_mesh_data(self):
        # Deliberate exclusion: snapshotting mesh.vertices (potentially millions
        # of elements) per loop would regress heavy scripts; these collections
        # are not element-removable mid-loop through these handles anyway.
        out = self.rewrite("for v in mesh.vertices:\n    v.co.x += 1.0")
        self.assertNotIn("_mixar_snapshot", out)

    def test_leaves_range(self):
        out = self.rewrite("for i in range(10):\n    pass")
        self.assertNotIn("_mixar_snapshot", out)

    def test_leaves_plain_name(self):
        out = self.rewrite("items = []\nfor o in items:\n    pass")
        self.assertNotIn("_mixar_snapshot", out)

    def test_leaves_values_call(self):
        # `.objects.values()` is already a list; the iterable is a Call, not an
        # Attribute, so it is not rewritten.
        out = self.rewrite("for o in coll.objects.values():\n    pass")
        self.assertNotIn("_mixar_snapshot", out)

    def test_comprehension_exclusions_and_idempotence(self):
        for source in (
            "[v for v in mesh.vertices]",
            "(o for o in list(scene.objects))",
            "[o async for o in scene.objects]",
        ):
            with self.subTest(source=source):
                self.assertEqual(self.rewrite(source), ast.unparse(ast.parse(source)))
        for source in (
            "for o in scene.objects:\n    pass",
            "objs = scene.objects\nfor o in objs:\n    pass",
            "[o for o in scene.objects]",
        ):
            with self.subTest(source=source):
                once = self.rewrite(source)
                self.assertEqual(once, self.rewrite(once))
                self.assertEqual(once.count("_mixar_snapshot("), 1)

    def test_wrapper_keeps_iterable_location(self):
        from mixar.modules.space_mixie_chat.core.sandbox_transform import (
            snapshot_collection_iterations,
        )
        source = (
            "names = [\n"
            "    o.name\n"
            "    for o in\n"
            "    bpy.data.objects\n"
            "]\n"
        )
        tree = ast.parse(source)
        iterable = tree.body[0].value.generators[0].iter
        position = (iterable.lineno, iterable.col_offset,
                    iterable.end_lineno, iterable.end_col_offset)
        self.assertEqual(position[0], 4)
        snapshot_collection_iterations(tree)
        call = tree.body[0].value.generators[0].iter
        self.assertIsInstance(call, ast.Call)
        self.assertEqual(
            (call.lineno, call.col_offset, call.end_lineno, call.end_col_offset),
            position,
        )
        self.assertEqual(call.func.lineno, 4)

    def test_multiline_for_keeps_iterable_location(self):
        from mixar.modules.space_mixie_chat.core.sandbox_transform import (
            snapshot_collection_iterations,
        )
        source = (
            "for o in (\n"
            "    scene.objects\n"
            "):\n"
            "    pass\n"
        )
        tree = snapshot_collection_iterations(ast.parse(source))
        call = tree.body[0].iter
        self.assertIsInstance(call, ast.Call)
        self.assertEqual((call.lineno, call.func.lineno), (2, 2))
        self.assertEqual((call.col_offset, call.end_col_offset), (4, 17))

        # The frame calling the snapshot reports the iterable's line, not the
        # `for` statement's.
        def snapshot(items):
            raise LookupError(sys._getframe(1).f_lineno)

        scene = types.SimpleNamespace(objects=_LiveCollection(["a"]))
        ns = {"scene": scene, "_mixar_snapshot": snapshot}
        with self.assertRaises(LookupError) as caught:
            exec(compile(tree, "<test>", "exec"), ns)  # noqa: S102
        self.assertEqual(caught.exception.args, (2,))

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
        self.assertIn("for obj in _mixar_snapshot(objs):", out)
        self.assertIn("objs = bpy.context.scene.collection.all_objects", out)

    def test_adjacent_binding_leaves_other_uses_intact(self):
        # Wrapping the loop (not the binding) means `objs.new(...)` still works —
        # a list snapshot has no `.new`, so rewriting the binding would break it.
        src = (
            "objs = bpy.data.objects\n"
            "for o in objs:\n"
            "    pass\n"
            "objs.new('X', None)"
        )
        out = self.rewrite(src)
        self.assertIn("for o in _mixar_snapshot(objs):", out)
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
        self.assertNotIn("_mixar_snapshot", out)


class TestSnapshotSemantics(unittest.TestCase):
    """Functional proof: the transform neutralises mutation-during-iteration."""

    def setUp(self):
        from mixar.modules.space_mixie_chat.core.sandbox_transform import (
            SNAPSHOT_FUNC_NAME, snapshot_collection_iterations, snapshot_iterable,
        )
        self.transform = snapshot_collection_iterations
        # The executor's binding for the reserved name.
        self.binding = {SNAPSHOT_FUNC_NAME: snapshot_iterable}

    def _run(self, script, apply_transform, scene=None):
        if scene is None:
            scene = types.SimpleNamespace(objects=_LiveCollection(["a", "b", "c"]))
        ns = {"scene": scene, **self.binding}
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

    def test_mutating_comprehensions(self):
        for expression in (
            "[scene.objects.remove(o) for o in scene.objects]",
            "{scene.objects.remove(o) for o in scene.objects}",
            "{o: scene.objects.remove(o) for o in scene.objects}",
            "list(scene.objects.remove(o) for o in scene.objects)",
            "[o for o in scene.objects if scene.objects.remove(o) is None]",
            "[o for group in [scene] for o in group.objects "
            "if group.objects.remove(o) is None]",
        ):
            with self.subTest(expression=expression):
                with self.assertRaises(RuntimeError):
                    self._run(expression, apply_transform=False)
                scene, _ = self._run(expression, apply_transform=True)
                self.assertEqual(scene.objects._items, [])

    def test_mutating_enumerate_loop(self):
        script = (
            "for i, o in enumerate(scene.objects):\n"
            "    scene.objects.remove(o)\n"
        )
        with self.assertRaises(RuntimeError):
            self._run(script, apply_transform=False)
        scene, _ = self._run(script, apply_transform=True)
        self.assertEqual(scene.objects._items, [])

    def test_generator_snapshots_before_resuming(self):
        script = (
            "items = (o for o in scene.objects)\n"
            "scene.objects.remove('b')\n"
            "result = list(items)\n"
        )
        _, original = self._run(script, apply_transform=False)
        _, protected = self._run(script, apply_transform=True)
        self.assertEqual(original['result'], ['a', 'c'])
        self.assertEqual(protected['result'], ['a', 'b', 'c'])

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

    def test_module_level_list_binding_does_not_break_snapshot(self):
        script = (
            "list = [1]\n"
            "[scene.objects.remove(o) for o in scene.objects]\n"
        )
        scene, ns = self._run(script, apply_transform=True)
        self.assertEqual(scene.objects._items, [])
        self.assertEqual(ns["list"], [1])

    def test_function_list_binding_does_not_break_snapshot(self):
        for script in (
            "def sweep(list):\n"
            "    return [scene.objects.remove(o) for o in scene.objects]\n"
            "sweep([1])\n",
            "def sweep():\n"
            "    list = [1]\n"
            "    for o in scene.objects:\n"
            "        scene.objects.remove(o)\n"
            "    return list\n"
            "sweep()\n",
        ):
            with self.subTest(script=script):
                scene, _ = self._run(script, apply_transform=True)
                self.assertEqual(scene.objects._items, [])

    def test_snapshot_never_asks_for_a_length_hint(self):
        # A scoped `__ws_data` collection view runs a full scope scan in both
        # `__len__` and `__iter__`; `list(view)` would call both.
        class _ScopedView:
            def __init__(self):
                self.len_calls = self.iter_calls = 0

            def __len__(self):
                self.len_calls += 1
                return 3

            def __iter__(self):
                self.iter_calls += 1
                return iter(["a", "b", "c"])

        for script in (
            "names = [o for o in scene.objects]\n",
            "names = []\nfor o in scene.objects:\n    names.append(o)\n",
        ):
            with self.subTest(script=script):
                view = _ScopedView()
                _, ns = self._run(
                    script, apply_transform=True,
                    scene=types.SimpleNamespace(objects=view),
                )
                self.assertEqual(ns["names"], ["a", "b", "c"])
                self.assertEqual((view.len_calls, view.iter_calls), (0, 1))

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
