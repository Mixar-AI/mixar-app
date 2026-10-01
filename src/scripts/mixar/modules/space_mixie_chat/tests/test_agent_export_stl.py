# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""STL in the agent export lane: ``spec["stl"]`` → ``wm.stl_export``
kwargs, the geometry-only runner path (no clip muting, material swap or
texture staging), a preflight that never blocks on materials, and the
header check in front of the re-import verification — pinned outside
Blender on fake objects."""

import os
import struct
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), *([".."] * 4)))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.space_mixie_chat.core import (  # noqa: E402
    agent_export,
    export_clips,
    export_destination,
    export_preflight,
    export_presets,
    export_reimport,
    export_verify,
)


def test_stl_kwargs_defaults_and_validation():
    assert export_presets.stl_kwargs({}) == {"global_scale": 1.0, "ascii_format": False}
    assert export_presets.stl_kwargs({"stl": {"scale": 1000, "ascii": True}}) == {
        "global_scale": 1000.0, "ascii_format": True}
    for bad in (0, -1, 1e7, float("nan")):
        with pytest.raises(ValueError):
            export_presets.stl_kwargs({"stl": {"scale": bad}})
    with pytest.raises(ValueError):
        export_presets.stl_kwargs({"stl": "big"})


def test_stl_preset_is_slicer_oriented_and_static():
    for use_case in export_presets.USE_CASES:
        kwargs = export_presets.preset_kwargs(use_case, "stl")
        assert kwargs["export_selected_objects"] is True and kwargs["apply_modifiers"] is True
        assert kwargs["use_scene_unit"] is False and kwargs["use_batch"] is False
        assert (kwargs["forward_axis"], kwargs["up_axis"]) == ("Y", "Z")
    report = export_presets.preset_report("other", "stl", {**kwargs, "global_scale": 10.0}, "none")
    assert report["exporter"] == "stl" and report["scale"] == 10.0 and report["axis_up"] == "Z"
    assert export_clips.animation_kwargs("stl", ["Walk"]) == ({}, "none", "")
    assert agent_export.EXTENSIONS["stl"] == ".stl"


class _Fake:
    """Attribute bag that is hashable like a real bpy ID (set membership)."""

    def __init__(self, **attrs):
        self.__dict__.update(attrs)


def _mesh(name):
    return _Fake(name=name, type="MESH", parent=None, modifiers=[], mode="OBJECT",
                 active_material_index=0, data=SimpleNamespace(materials=[]),
                 select_set=lambda *_: None)


def test_run_export_stl_skips_material_and_clip_machinery(monkeypatch, tmp_path):
    meshes = [_mesh("Box"), _mesh("Lid")]
    calls, seen = [], {}
    monkeypatch.setattr(agent_export, "bpy", SimpleNamespace(
        context=SimpleNamespace(view_layer=SimpleNamespace(objects=SimpleNamespace(active=None)),
                                selected_objects=[], scene=SimpleNamespace()),
        ops=SimpleNamespace(object=SimpleNamespace(select_all=MagicMock(poll=lambda: True),
                                                   mode_set=MagicMock()))))
    monkeypatch.setattr(agent_export, "export_targets", lambda spec: meshes)
    monkeypatch.setattr(agent_export, "preflight_meshes", lambda spec, m: {"ready": True})

    def forbidden(*_a, **_k):
        raise AssertionError("STL must not touch materials, textures or clips")

    for name in ("_temporary_export_materials", "staged_obj_textures", "clip_selection"):
        monkeypatch.setattr(agent_export, name, forbidden)

    def exporter(filepath, **kwargs):
        calls.append(kwargs)
        open(filepath, "wb").write(b"\0" * 80 + struct.pack("<I", 0))
        return {"FINISHED"}

    monkeypatch.setattr(agent_export, "_exporter", lambda fmt: exporter)
    monkeypatch.setattr(agent_export, "verify_export", lambda p, f, e: {
        **seen.setdefault("expected", e), "checked": True, "issues": [], "passed": True,
        "animations": [], "bounds": [60.0, 60.0, 60.0]})
    export_destination.set_destination("sess", str(tmp_path / "Part.stl"))
    result = agent_export.run_export("sess", {
        "format": "stl", "target_scope": "scene", "animations": ["Walk"],
        "stl": {"scale": 1000.0, "ascii": True}})
    assert result["success"] is True, result
    kwargs = calls[0]
    assert kwargs["global_scale"] == 1000.0 and kwargs["ascii_format"] is True
    assert kwargs["export_selected_objects"] is True and kwargs["use_scene_unit"] is False
    assert kwargs["apply_modifiers"] is True
    assert "path_mode" not in kwargs and "export_animations" not in kwargs
    expected = seen["expected"]
    assert expected["joined"] is True and expected["images_expected"] == 0
    assert expected["clips"] is None and expected["stl_scale"] == 1000.0
    assert result["clips"] == [] and "geometry-only" in result["warning"]
    assert result["preset"]["scale"] == 1000.0 and result["preset"]["ascii"] is True
    assert result["filepath_basename"] == "Part.stl"


def test_preflight_never_blocks_stl_on_materials():
    image = SimpleNamespace(name="Albedo", packed_file=None)
    material = SimpleNamespace(name="Body", use_nodes=True, node_tree=SimpleNamespace(
        nodes=[SimpleNamespace(image=image, node_tree=None)]))
    obj = SimpleNamespace(name="Box", rotation_euler=(0, 0, 0), scale=(2, 2, 2),
                          modifiers=[SimpleNamespace(name="Bevel", type="BEVEL")],
                          data=SimpleNamespace(materials=[material], uv_layers=[]))
    glb = export_preflight.preflight_meshes({"format": "glb"}, [obj])
    assert glb["checks"]["packed_images"]["failed"] == 1
    stl = export_preflight.preflight_meshes({"format": "stl"}, [obj])
    for key in export_preflight.MATERIAL_CHECKS:
        check = stl["checks"][key]
        assert check["failed"] == 0 and check["passed"] == 1 and check["skipped"] is True
        assert "STL" in check["label"]
    # Transforms and modifiers still apply to a printed solid.
    assert stl["checks"]["transforms"]["failed"] == 1
    assert stl["checks"]["modifiers"]["failed"] == 1 and stl["ready"] is False


def test_stl_header_detection(tmp_path):
    binary = tmp_path / "part.stl"
    binary.write_bytes(b"solid but binary".ljust(80, b"\0") + struct.pack("<I", 2) + b"\0" * 100)
    assert export_reimport.check_stl_header(str(binary), binary.stat().st_size) == ("binary", 2)
    ascii_stl = tmp_path / "ascii.stl"
    ascii_stl.write_bytes(b"solid part\n" + b"facet normal 0 0 1\n" * 10 + b"endsolid part\n")
    assert export_reimport.check_stl_header(str(ascii_stl), ascii_stl.stat().st_size) == ("ascii", None)
    junk = tmp_path / "junk.stl"
    junk.write_bytes(b"\x01" * 400)
    result = export_verify.verify_export(str(junk), "stl", {"mesh_count": 1, "joined": True})
    assert result["method"] == "reimport" and result["checked"] is False
    assert any("neither a binary nor an ASCII STL" in i for i in result["issues"])
    tiny = tmp_path / "tiny.stl"
    tiny.write_bytes(b"\0" * 80 + struct.pack("<I", 0))
    assert any("empty" in i for i in export_verify.verify_export(str(tiny), "stl", {})["issues"])


def test_stl_report_gives_file_unit_bounds_and_metres(monkeypatch):
    monkeypatch.setattr(export_reimport, "_bounds", lambda meshes: [60.0, 60.0, 30.0])
    monkeypatch.setattr(export_reimport, "_open_edges", lambda meshes: 4)
    result = {"issues": []}
    export_reimport._stl_report([object()], result, 1000.0)
    assert result["bounds"] == [60.0, 60.0, 30.0] and result["dimensions_m"] == [0.06, 0.06, 0.03]
    assert result["up_axis"] == "+Z" and result["non_manifold_edges"] == 4
    assert any("not watertight" in i for i in result["issues"])
