# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Smart UV submits check what is uploaded and record where the source is.

* The 80,000-triangle limit counts the BASE mesh (``obj.data``): the GLB export
  runs without ``export_apply``, so a Subsurf cube uploads 12 triangles and a
  Decimated 100k grid uploads 100k. Counting the evaluated mesh refused the
  first and let the second through.
* Both submit paths (the Moodboard node and ``mixie.agent_tripo_uv``) record
  the source's world box and hand it to the result hook, which fits the
  normalised result back onto it before renaming.
"""

import sys
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import numpy as np
import pytest

sys.modules.setdefault("keyring", MagicMock())

from mixar.modules.hunyuan.core import tripo_uv_enqueue as T  # noqa: E402
from mixar.modules.hunyuan.core import tripo_uv_placement as P  # noqa: E402


class Polygons:
    def __init__(self, sizes):
        self.sizes = np.asarray(sizes, dtype=np.int32)

    def __len__(self):
        return len(self.sizes)

    def foreach_get(self, attr, out):
        assert attr == "loop_total"
        out[:] = self.sizes


class Vertices:
    def __init__(self, co):
        self.co = np.asarray(co, dtype=np.float64).reshape(-1, 3)

    def __len__(self):
        return len(self.co)

    def foreach_get(self, attr, out):
        assert attr == "co"
        out[:] = self.co.ravel()


def mesh(name, polygon_sizes, evaluated_sizes=None, co=None, location=(0, 0, 0)):
    """A mesh object whose base mesh and evaluated mesh (modifiers) differ."""
    evaluated = NS(data=NS(polygons=Polygons(
        polygon_sizes if evaluated_sizes is None else evaluated_sizes)))
    matrix = np.identity(4)
    matrix[:3, 3] = location
    co = [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)] if co is None else co
    return NS(name=name, type='MESH',
              data=NS(polygons=Polygons(polygon_sizes), vertices=Vertices(co)),
              matrix_world=matrix.tolist(),
              evaluated_get=lambda depsgraph: evaluated)


# ---------------------------------------------------------------------------
# Bug 2: count the base mesh, which is what the GLB carries
# ---------------------------------------------------------------------------


def test_a_subsurf_cube_counts_its_twelve_base_triangles():
    # 6 quads; Subsurf level 7 evaluates to 98,304 quads = 196,608 triangles.
    cube = mesh("Cube", [4] * 6, evaluated_sizes=[4] * 98_304)
    assert T.equivalent_triangles([cube]) == 12
    T.check_triangle_limit([cube])  # not refused


def test_a_decimated_grid_counts_its_full_base_mesh_and_is_refused():
    # 50,000 quads = 100,000 base triangles; Decimate 0.5 evaluates to ~50k.
    grid = mesh("Grid", [4] * 50_000, evaluated_sizes=[3] * 50_000)
    assert T.equivalent_triangles([grid]) == 100_000
    with pytest.raises(ValueError, match="100,000"):
        T.check_triangle_limit([grid])


def test_an_ngon_counts_n_minus_two_and_meshes_sum():
    ngons = mesh("Ngons", [40] * 3 + [3, 4])
    quads = mesh("Quads", [4] * 10)
    light = NS(name="Light", type='LIGHT')
    empty = mesh("Empty", [])
    assert T.equivalent_triangles([ngons, quads, light, empty]) == 3 * 38 + 1 + 2 + 20


def test_exactly_the_limit_passes_and_one_more_is_refused():
    T.check_triangle_limit([mesh("At", [4] * 40_000)])
    with pytest.raises(ValueError, match="80,001"):
        T.check_triangle_limit([mesh("Over", [4] * 40_000 + [3])])


def test_the_count_never_evaluates_the_depsgraph():
    source = T.equivalent_triangles.__code__.co_names
    assert "evaluated_get" not in source
    assert "evaluated_depsgraph_get" not in source


# ---------------------------------------------------------------------------
# Bug 1: the source box rides with the job to the result hook
# ---------------------------------------------------------------------------


def test_finalize_places_the_import_before_renaming_it(monkeypatch):
    from mixar.modules.common.job_queue.core import model_io

    calls = []
    monkeypatch.setattr(T, "place_over_source",
                        lambda names, box: calls.append(("place", names, box)) or True)
    monkeypatch.setattr(model_io, "rename_imported_object",
                        lambda names, target: calls.append(("rename", names, target))
                        or target)
    box = ((0, 0, 0), (1, 2, 3))

    assert T.finalize_uv_import("Src.001", "Src", False, source_bounds=box) == "Src_uv"
    assert calls == [("place", "Src.001", box), ("rename", "Src.001", "Src_uv")]


def test_finalize_without_a_box_leaves_the_import_in_place(monkeypatch):
    from mixar.modules.common.job_queue.core import model_io

    placed = []
    monkeypatch.setattr(T, "place_over_source", lambda *a: placed.append(a))
    monkeypatch.setattr(model_io, "rename_imported_object", lambda names, target: target)
    assert T.finalize_uv_import("Src.001", "Src", False) == "Src_uv"
    assert placed == []


def test_the_agent_submit_records_the_source_box_for_its_hook(monkeypatch):
    from mixar.modules.common import generation_params

    source = mesh("Hero", [4] * 6, location=(-4, 0, 1))
    captured = {}
    monkeypatch.setattr(T, "_export_single_object", lambda ctx, obj: (b"glb", "export.glb"))
    monkeypatch.setattr(generation_params, "resolve_model_slug", lambda *a: "tripo_uv_v1")
    monkeypatch.setattr(generation_params, "assemble_payload", lambda s, p, payload, m: payload)
    monkeypatch.setattr(T, "enqueue_generation",
                        lambda **kw: captured.update(kw) or NS(id="job"))
    finalized = []
    monkeypatch.setattr(T, "finalize_uv_import",
                        lambda names, src, bake, source_bounds=None:
                        finalized.append((names, src, bake, source_bounds)) or "Hero_uv")
    monkeypatch.setattr(T, "add_uv_atlas_to_board", lambda *a, **k: None)

    context = NS(scene=NS(name="Scene"))
    T.enqueue_tripo_uv_job(context=context, obj=source, bake=False)
    # The source moves after submit; the result still lands where it was sent from.
    source.matrix_world = np.identity(4).tolist()
    assert captured["on_imported"](NS(result_data={}), "Hero.001") == "Hero_uv"

    expected = ((-5.0, -1.0, 0.0), (-3.0, 1.0, 2.0))
    assert finalized == [("Hero.001", "Hero", False, expected)]


def test_the_agent_submit_refuses_before_recording_or_exporting(monkeypatch):
    exported = []
    monkeypatch.setattr(T, "_export_single_object", lambda *a: exported.append(a))
    heavy = mesh("Heavy", [4] * 50_000, evaluated_sizes=[3] * 50_000)
    with pytest.raises(ValueError, match="100,000"):
        T.enqueue_tripo_uv_job(context=NS(scene=NS(name="Scene")), obj=heavy)
    assert exported == []


class ViewObjects(list):
    active = None

    def __contains__(self, name):
        return any(obj.name == name for obj in self)


def _node_run(monkeypatch, sources, export=None):
    from mixar.modules.common import generation_params
    from mixar.modules.common.job_queue.core import model_io
    from mixar.modules.moodboard.core import node_mesh_execution as nme

    for obj in sources:
        obj.select_get = lambda: False
        obj.select_set = lambda state: None
    view_objects = ViewObjects(sources)
    context = NS(scene=NS(name="Scene"), view_layer=NS(objects=view_objects))
    node = NS(node_id="uv-node", action_type='UV_UNWRAP', prompt="")
    hooks = []

    def hook(*args, **kwargs):
        hooks.append(kwargs)
        return lambda job, names: names

    monkeypatch.setattr(nme, "mesh_input_objects", lambda *_: list(sources))
    monkeypatch.setattr(nme, "node_service_key", lambda node: "tripo_uv")
    monkeypatch.setattr(nme, "node_model_slug", lambda node: "tripo_uv_v1")
    monkeypatch.setattr(generation_params, "resolve_service_key", lambda *_: "tripo_uv")
    monkeypatch.setattr(generation_params, "resolve_model_slug", lambda *_: "tripo_uv_v1")
    monkeypatch.setattr(generation_params, "assemble_payload", lambda s, p, payload, m: payload)
    monkeypatch.setattr(nme, "collect_node_params", lambda *_: {"bake": True})
    monkeypatch.setattr(nme, "ensure_graph_listener", lambda *_: None)
    monkeypatch.setattr(nme, "enqueue_generation", lambda **_: NS(id="job"))
    monkeypatch.setattr(nme, "_mesh_result_hook", hook)
    monkeypatch.setattr(model_io, "export_selected_mesh",
                        export or (lambda ctx, fmt: (b"glb", "export.glb")))
    return nme, context, node, hooks


def test_the_node_submit_records_the_union_of_its_source_meshes(monkeypatch):
    a = mesh("A", [4] * 6, location=(-3, 0, 0))
    b = mesh("B", [4] * 6, location=(4, 1, 2))
    nme, context, node, hooks = _node_run(monkeypatch, [a, b])

    nme._run_mesh_feature(context, node, None)

    assert len(hooks) == 1
    assert hooks[0]["uv_bake"] is True
    assert hooks[0]["base_name"] == "A"
    assert hooks[0]["uv_source_bounds"] == ((-4.0, -1.0, -1.0), (5.0, 2.0, 3.0))


def test_the_node_submit_refuses_a_heavy_base_mesh_before_export(monkeypatch):
    exported = []
    heavy = mesh("Heavy", [4] * 50_000, evaluated_sizes=[3] * 50_000)
    nme, context, node, hooks = _node_run(
        monkeypatch, [heavy], export=lambda *a: exported.append(a))

    with pytest.raises(ValueError, match="100,000"):
        nme._run_mesh_feature(context, node, None)
    assert exported == [] and hooks == []


def test_other_mesh_features_record_no_uv_box(monkeypatch):
    nme, context, node, hooks = _node_run(monkeypatch, [mesh("A", [4] * 6)])
    node.action_type = 'RETOPOLOGY'
    monkeypatch.setattr(nme, "node_service_key", lambda node: "tripo_retopology")

    nme._run_mesh_feature(context, node, None)
    assert hooks[0]["uv_bake"] is None
    assert hooks[0]["uv_source_bounds"] is None


def test_the_node_result_hook_hands_the_box_to_finalize(monkeypatch):
    from mixar.modules.moodboard.core import node_graph
    from mixar.modules.moodboard.core import node_mesh_execution as nme

    scene = NS(name="Scene")
    node = NS(node_id="uv-node")
    monkeypatch.setattr(nme, "bpy", NS(data=NS(scenes={"Scene": scene})))
    monkeypatch.setattr(nme, "action_node_by_id", lambda sc, node_id: node)
    monkeypatch.setattr(node_graph, "create_asset_result", lambda *a: None)
    finalized = []
    monkeypatch.setattr(T, "finalize_uv_import",
                        lambda names, src, bake, source_bounds=None:
                        finalized.append((names, src, bake, source_bounds)) or "Src_uv")
    monkeypatch.setattr(T, "add_uv_atlas_to_board", lambda *a, **k: None)
    box = ((0, 0, 0), (1, 1, 1))

    hook = nme._mesh_result_hook("Scene", "uv-node", base_name="Src", uv_bake=True,
                                 uv_source_bounds=box)
    assert hook(NS(result_data={}), "Src.001") == "Src_uv"
    assert finalized == [("Src.001", "Src", True, box)]


def test_the_placement_module_stays_free_of_bpy_at_import():
    # Pure maths + numpy at module scope: the hook closures carry plain floats.
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(P))
    top_imports = {
        alias.name for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    } | {node.module for node in tree.body if isinstance(node, ast.ImportFrom)}
    assert "bpy" not in top_imports and "mathutils" not in top_imports
