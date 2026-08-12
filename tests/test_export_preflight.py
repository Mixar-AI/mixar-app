# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Standalone unit contracts for deterministic export preflight."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parents[1]


def _load():
    path = ROOT / "src/scripts/mixar/modules/space_mixie_chat/core/export_preflight.py"
    spec = importlib.util.spec_from_file_location("export_preflight_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Nodes(list):
    def get(self, name):
        return next((node for node in self if getattr(node, "name", None) == name), None)


def test_transform_tolerance_ignores_location_and_preserves_armatures():
    module = _load()
    obj = SimpleNamespace(
        rotation_euler=(1e-6, 0, 0), scale=(1, 1 + 1e-6, 1),
        location=(100, 200, 300), modifiers=[SimpleNamespace(name="Rig", type="ARMATURE")],
        data=SimpleNamespace(materials=[], uv_layers=[]),
    )
    failures = module.inspect_mesh(obj)
    assert failures["transforms"] == []
    assert failures["modifiers"] == []


def test_recursive_material_images_are_unique_and_packed_images_pass():
    module = _load()
    packed = SimpleNamespace(name="Packed", packed_file=object())
    child = SimpleNamespace(nodes=Nodes([SimpleNamespace(image=packed, node_tree=None)]))
    root = SimpleNamespace(nodes=Nodes([
        SimpleNamespace(image=packed, node_tree=None),
        SimpleNamespace(image=None, node_tree=child),
    ]))
    material = SimpleNamespace(name="Mat", use_nodes=True, node_tree=root)
    assert module.material_images(material) == [packed]


def test_nested_unpacked_image_and_modifier_report_concrete_reasons():
    module = _load()
    image = SimpleNamespace(name="Albedo", packed_file=None)
    child = SimpleNamespace(nodes=Nodes([SimpleNamespace(image=image, node_tree=None)]))
    material = SimpleNamespace(name="Body", use_nodes=True,
                               node_tree=SimpleNamespace(nodes=Nodes([
                                   SimpleNamespace(image=None, node_tree=child),
                               ])))
    obj = SimpleNamespace(
        rotation_euler=(0, 0, 0), scale=(1, 1, 1),
        modifiers=[SimpleNamespace(name="Bevel", type="BEVEL")],
        data=SimpleNamespace(materials=[material], uv_layers=[object()]),
    )
    failures = module.inspect_mesh(obj)
    assert failures["modifiers"] == ["unapplied modifiers: Bevel"]
    assert failures["packed_images"] == ["Body: unpacked images: Albedo"]


def test_selected_named_and_scene_resolution_share_one_function():
    module = _load()
    mesh_a = SimpleNamespace(name="A", type="MESH")
    mesh_b = SimpleNamespace(name="B", type="MESH")
    light = SimpleNamespace(name="Lamp", type="LIGHT")
    objects = {obj.name: obj for obj in (mesh_a, mesh_b, light)}
    module.bpy = SimpleNamespace(
        data=SimpleNamespace(objects=SimpleNamespace(get=objects.get, __getitem__=objects.__getitem__)),
        context=SimpleNamespace(selected_objects=[mesh_a, light],
                                scene=SimpleNamespace(objects=[mesh_a, mesh_b, light])),
    )
    # Blender collections support both get() and subscription; use a tiny proxy.
    class ObjectProxy:
        get = objects.get
        def __getitem__(self, key):
            return objects[key]
    module.bpy.data.objects = ObjectProxy()
    assert module.resolve_targets("selected") == [mesh_a]
    assert module.resolve_targets("named", ["B", "Lamp"]) == [mesh_b]
    assert module.resolve_targets("scene") == [mesh_a, mesh_b]


def test_report_aggregates_each_check_per_mesh():
    module = _load()
    good = SimpleNamespace(name="Good", type="MESH", rotation_euler=(0, 0, 0),
                           scale=(1, 1, 1), modifiers=[],
                           data=SimpleNamespace(materials=[], uv_layers=[]))
    bad = SimpleNamespace(name="Bad", type="MESH", rotation_euler=(0.1, 0, 0),
                          scale=(1, 1, 1), modifiers=[],
                          data=SimpleNamespace(materials=[], uv_layers=[]))
    module.resolve_targets = lambda *_args: [good, bad]
    report = module.run_preflight({"target_scope": "scene"})
    assert report["mesh_count"] == 2
    assert report["ready"] is False
    assert report["checks"]["transforms"]["passed"] == 1
    assert report["checks"]["transforms"]["failed_meshes"] == ["Bad"]


def test_markdown_report_bounds_failure_details():
    module = _load()
    report = {"mesh_count": 6, "checks": {key: {
        "label": module.CHECK_LABELS[key], "passed": 0, "failed": 6,
        "failures": [{"mesh": f"Mesh {index}", "reasons": ["bad | value"]}
                     for index in range(6)],
    } for key in module.CHECK_ORDER}}
    markdown = module.format_report_markdown(report, detail_limit=2)
    assert "0 / 6" in markdown
    assert "+4 more" in markdown
    assert "Mesh 2" not in markdown
    assert "\\|" in markdown
