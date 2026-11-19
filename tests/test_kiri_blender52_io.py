# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""The vendored KIRI add-on's Blender 5.2 modifier-input patch.

Blender 5.2 removed ID-property access on modifiers: ``mod['Socket_N']``
raises TypeError for reads and writes, and geometry-nodes inputs live at
``mod.properties.inputs.<Socket_N>.value``. The fakes below model exactly
that (object ID properties still work), so code still subscripting a
modifier fails here the way it fails in the app.

The callbacks and import lines are AST-extracted from the real source and
run against those fakes; the add-on itself needs Blender and GPU modules.
"""

import ast
import importlib.util
import sys
import types
import warnings
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

KIRI_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "src/scripts/addons_core/kiri_3dgs_render/__init__.py"
)
SPLAT_RENDER_CAMERA = (
    Path(__file__).resolve().parents[1]
    / "src/scripts/mixar/modules/moodboard/core/splat_render_camera.py"
)
SOURCE_TEXT = KIRI_SOURCE.read_text(encoding="utf-8")
with warnings.catch_warnings():
    # The vendored file has an upstream invalid escape sequence in a string.
    warnings.simplefilter("ignore", SyntaxWarning)
    TREE = ast.parse(SOURCE_TEXT)

GN = "KIRI_3DGS_Render_GN"
MODES = ("Enable Camera Updates", "Disable Camera Updates", "Show As Point Cloud")
SOCKETS = [f"Socket_{n}" for n in (*range(2, 36), 50, 54, 61)]


# --------------------------------------------------------------------------- #
# Blender 5.2 fakes
# --------------------------------------------------------------------------- #

class _Modifier:
    """A GN modifier as Blender 5.2 exposes it: no ID-property access."""

    def __init__(self):
        self.properties = NS(inputs=NS(**{s: NS(value=None) for s in SOCKETS}))
        self.show_viewport = None

    def __getitem__(self, key):
        raise TypeError("bpy_struct[key] = val: id properties not supported for this type")

    def __setitem__(self, key, value):
        raise TypeError("bpy_struct[key] = val: id properties not supported for this type")

    def value(self, socket):
        return getattr(self.properties.inputs, socket).value


class _Object(dict):
    """An Object: ID properties (item assignment) still work on 5.2."""

    def __init__(self, with_gn=True):
        super().__init__()
        self.modifiers = {GN: _Modifier()} if with_gn else {}
        self.update_tag = Mock()


def _fake_bpy(active, area=None):
    return NS(
        context=NS(
            view_layer=NS(objects=NS(active=active)),
            screen=NS(areas=[]),
            area=area,
        ),
        app=NS(timers=NS(register=Mock())),
        data=NS(materials={}),
    )


# --------------------------------------------------------------------------- #
# AST extraction
# --------------------------------------------------------------------------- #

def _function_node(name, tree=TREE):
    return next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name
    )


def _helpers():
    """The MIXAR PATCH helper, when the source has one."""
    env = {}
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == "mixar_gn_input":
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(KIRI_SOURCE), "exec"), env)
    return env


def _function(name, **env):
    env = {**_helpers(), **env}
    node = _function_node(name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(KIRI_SOURCE), "exec"), env)
    return env[name]


def _import_execute():
    cls = next(
        n for n in TREE.body
        if isinstance(n, ast.ClassDef) and n.name == "SNA_OT_Dgs_Render_Import_Ply_E0A3A"
    )
    return next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "execute")


def _import_socket_writes():
    """The import operator's statements that write Socket_50 / Socket_61."""
    found = []
    for node in ast.walk(_import_execute()):
        if isinstance(node, ast.Assign):
            text = ast.get_source_segment(SOURCE_TEXT, node) or ""
            if "'Socket_50'" in text or "'Socket_61'" in text:
                found.append(node)
    return found


def _pinned_functions():
    camera = _function_node("sna_update_camera_single_time_9EF18")
    return {
        "sna_update_update_mode_868D4": _function_node("sna_update_update_mode_868D4"),
        "sna_update_cam_update_DE26E": _function_node("sna_update_cam_update_DE26E"),
        "update_gaussian_splat_camera": _function_node("update_gaussian_splat_camera", camera),
        "SNA_OT_Dgs_Render_Import_Ply_E0A3A.execute": _import_execute(),
    }


# --------------------------------------------------------------------------- #
# update_mode
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("mode", MODES)
def test_update_mode_updates_the_non_active_owner(mode):
    owner, active = _Object(), _Object(with_gn=False)
    callback = _function("sna_update_update_mode_868D4", bpy=_fake_bpy(active))

    callback(NS(id_data=owner, update_mode=mode), NS(area=None, screen=None))

    modifier = owner.modifiers[GN]
    assert modifier.value("Socket_50") == mode
    assert modifier.show_viewport is (mode != "Disable Camera Updates")
    assert owner["update_rot_to_cam"] is (mode == "Enable Camera Updates")
    owner.update_tag.assert_called_once()
    assert not active


def test_update_mode_without_the_modifier_is_a_no_op():
    owner, active = _Object(with_gn=False), _Object(with_gn=False)
    callback = _function("sna_update_update_mode_868D4", bpy=_fake_bpy(active))

    callback(NS(id_data=owner, update_mode=MODES[0]), NS(area=None, screen=None))

    assert not owner
    owner.update_tag.assert_not_called()


# --------------------------------------------------------------------------- #
# cam_update
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("enabled", [True, False])
def test_cam_update_without_an_area_only_writes_the_socket(enabled):
    owner = _Object()
    bpy = _fake_bpy(_Object(with_gn=False))
    callback = _function(
        "sna_update_cam_update_DE26E", bpy=bpy, sna_update_camera_single_time_9EF18=Mock()
    )

    callback(NS(id_data=owner, cam_update=enabled), NS(area=None, screen=None))

    assert owner.modifiers[GN].value("Socket_54") is enabled
    bpy.app.timers.register.assert_not_called()


def test_cam_update_from_a_3d_view_enters_camera_view_and_schedules_the_update():
    owner = _Object()
    region_3d = NS(view_perspective="PERSP")
    area = NS(type="VIEW_3D", spaces=NS(active=NS(region_3d=region_3d)))
    bpy = _fake_bpy(_Object(with_gn=False), area=area)
    camera_update = Mock()
    callback = _function(
        "sna_update_cam_update_DE26E", bpy=bpy, sna_update_camera_single_time_9EF18=camera_update
    )

    callback(NS(id_data=owner, cam_update=True), NS(area=area, screen=None))

    assert owner.modifiers[GN].value("Socket_54") is True
    assert region_3d.view_perspective == "CAMERA"
    bpy.app.timers.register.assert_called_once()
    bpy.app.timers.register.call_args.args[0]()
    camera_update.assert_called_once_with()


# --------------------------------------------------------------------------- #
# PLY import + the camera-update timer target
# --------------------------------------------------------------------------- #

def test_import_writes_update_mode_and_material_through_the_inputs():
    nodes = _import_socket_writes()
    assert len(nodes) == 2
    active = _Object()
    material = object()
    bpy = _fake_bpy(active)
    bpy.data.materials["KIRI_3DGS_Render_Material"] = material
    env = {**_helpers(), "bpy": bpy}

    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(KIRI_SOURCE), "exec"), env)

    modifier = active.modifiers[GN]
    assert modifier.value("Socket_50") == "Disable Camera Updates"
    assert modifier.value("Socket_61") is material


def test_camera_update_writes_matrices_through_the_inputs():
    node = _function_node(
        "update_gaussian_splat_camera", _function_node("sna_update_camera_single_time_9EF18")
    )
    env = _helpers()
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(KIRI_SOURCE), "exec"), env)
    obj = _Object()
    view = [[10 * r + c for c in range(4)] for r in range(4)]
    proj = [[100 + 10 * r + c for c in range(4)] for r in range(4)]

    assert env["update_gaussian_splat_camera"](obj, view, proj, 640, 480) is True

    modifier = obj.modifiers[GN]
    assert modifier.value("Socket_2") == view[0][0]
    assert modifier.value("Socket_17") == view[3][3]
    assert modifier.value("Socket_18") == proj[0][0]
    assert modifier.value("Socket_33") == proj[3][3]
    assert (modifier.value("Socket_34"), modifier.value("Socket_35")) == (640, 480)


# --------------------------------------------------------------------------- #
# Mixar's enable_render_updates against the patched update_mode callback
# --------------------------------------------------------------------------- #

class _SplatProps:
    """sna_dgs_object_properties whose update_mode setter runs KIRI's callback."""

    def __init__(self, owner):
        object.__setattr__(self, "id_data", owner)
        object.__setattr__(self, "update_mode", MODES[1])
        object.__setattr__(self, "cam_update", False)

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)
        if name == "update_mode":
            callback = _function(
                "sna_update_update_mode_868D4", bpy=_fake_bpy(_Object(with_gn=False))
            )
            callback(self, NS(area=None, screen=None))


def _splat(kind="MESH", with_gn=True):
    obj = _Object(with_gn=with_gn)
    obj.name, obj.type = "Splat", kind
    obj.sna_dgs_object_properties = _SplatProps(obj)
    if with_gn:
        obj.modifiers[GN].show_viewport = False  # as KIRI's import leaves it
    return obj


@pytest.fixture
def splat_render_camera(monkeypatch):
    """splat_render_camera loaded against minimal bpy / logging stubs."""
    handlers = types.ModuleType("bpy.app.handlers")
    handlers.persistent = lambda fn: fn
    bpy = types.ModuleType("bpy")
    bpy.app = types.ModuleType("bpy.app")
    bpy.app.handlers = handlers
    bpy.data = NS(materials={})
    bpy.context = NS(scene=NS(name="Scene", render=NS(use_lock_interface=True)))
    logging_stub = types.ModuleType("mixar.config.logging_config")
    logging_stub.get_logger = lambda _name: Mock()
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    monkeypatch.setitem(sys.modules, "bpy.app", bpy.app)
    monkeypatch.setitem(sys.modules, "bpy.app.handlers", handlers)
    monkeypatch.setitem(sys.modules, "mixar.config.logging_config", logging_stub)
    spec = importlib.util.spec_from_file_location(
        "test_kiri_splat_render_camera", SPLAT_RENDER_CAMERA
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_enable_render_updates_keeps_the_render_gn_viewport_off(splat_render_camera):
    """KIRI's proxy is built from the evaluated mesh: a live GN quadruples it."""
    splat = _splat()

    splat_render_camera.enable_render_updates([splat])

    props = splat.sna_dgs_object_properties
    assert props.update_mode == "Enable Camera Updates"
    assert props.cam_update is True
    assert splat.modifiers[GN].value("Socket_50") == "Enable Camera Updates"
    assert splat.modifiers[GN].show_viewport is False


@pytest.mark.parametrize("kind, with_gn", [("EMPTY", True), ("MESH", False)])
def test_enable_render_updates_skips_non_splats(splat_render_camera, kind, with_gn):
    obj = _splat(kind, with_gn)

    splat_render_camera.enable_render_updates([obj])

    props = obj.sna_dgs_object_properties
    assert props.update_mode == MODES[1]
    assert props.cam_update is False
    if with_gn:
        assert obj.modifiers[GN].show_viewport is False


# --------------------------------------------------------------------------- #
# Source pin
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("name", list(_pinned_functions()))
def test_no_modifier_socket_subscripts_remain(name):
    offenders = [
        ast.get_source_segment(SOURCE_TEXT, node)
        for node in ast.walk(_pinned_functions()[name])
        if isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
        and node.slice.value.startswith("Socket_")
    ]
    assert offenders == []
