# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure-Python tests for the group->BSDF link trace + repair and occlusion report.

Exercises the headless-safe logic behind the paint-stack render-sync fix:
- ``bsdf_socket_driven_by_node`` backward DFS (direct, via-intermediate, foreign, none)
- ``ensure_group_drives_bsdf`` conservative relink (repairs missing/foreign links,
  leaves group-driven chains — including the AO-multiply chain — untouched)
- ``_enabled_layers_above_base`` occlusion report (index 0 == TOP)

The bpy shader graph is faked; the trace/relink code under test is bpy-runtime code
otherwise only verifiable in a live Blender run.
"""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
PAINT = ROOT / "src/scripts/mixar/modules/paint"
BSDF_PY = PAINT / "core/io/utils/bsdf_connections.py"
COMMON_PY = PAINT / "core/agent_tools/_common.py"


# --------------------------------------------------------------------------- #
# Minimal fake bpy shader-graph datamodel
# --------------------------------------------------------------------------- #
class _SocketColl(list):
    def get(self, name):
        for sock in self:
            if sock.name == name:
                return sock
        return None


class _Socket:
    def __init__(self, name, node):
        self.name = name
        self.node = node
        self.links = []


class _Node:
    def __init__(self, name, type=""):
        self.name = name
        self.type = type
        self.inputs = _SocketColl()
        self.outputs = _SocketColl()

    def add_input(self, name):
        sock = _Socket(name, self)
        self.inputs.append(sock)
        return sock

    def add_output(self, name):
        sock = _Socket(name, self)
        self.outputs.append(sock)
        return sock


class _Link:
    def __init__(self, from_socket, to_socket):
        self.from_socket = from_socket
        self.to_socket = to_socket
        self.from_node = from_socket.node
        self.to_node = to_socket.node


class _Links:
    def __init__(self, store):
        self._store = store

    def new(self, from_socket, to_socket):
        # An input socket holds at most one link — replace any existing one.
        for existing in list(to_socket.links):
            to_socket.links.remove(existing)
            if existing in self._store:
                self._store.remove(existing)
        link = _Link(from_socket, to_socket)
        to_socket.links.append(link)
        self._store.append(link)
        return link


class _NodeTree:
    def __init__(self):
        self.nodes = []
        self._links = []
        self.links = _Links(self._links)

    def add_node(self, node):
        self.nodes.append(node)
        return node


class _Material:
    def __init__(self, node_tree):
        self.node_tree = node_tree


def _load_bsdf_module(monkeypatch):
    """Load bsdf_connections.py with its relative imports satisfied by stubs."""
    monkeypatch.setitem(sys.modules, "bpy", types.SimpleNamespace(context=types.SimpleNamespace(view_layer=None)))

    def _pkg(name):
        mod = types.ModuleType(name)
        mod.__path__ = []  # mark as a package so relative imports resolve
        monkeypatch.setitem(sys.modules, name, mod)
        return mod

    for name in (
        "mixar",
        "mixar.config",
        "mixar.modules",
        "mixar.modules.paint",
        "mixar.modules.paint.core",
        "mixar.modules.paint.core.io",
        "mixar.modules.paint.core.io.utils",
        "mixar.modules.paint.utils",
    ):
        _pkg(name)

    log_mod = types.ModuleType("mixar.config.logging_config")
    log_mod.get_logger = lambda *a, **k: MagicMock()
    monkeypatch.setitem(sys.modules, "mixar.config.logging_config", log_mod)

    bc_mod = types.ModuleType("mixar.modules.paint.utils.blender_commons")
    bc_mod.get_active_material = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "mixar.modules.paint.utils.blender_commons", bc_mod)

    const_mod = types.ModuleType("mixar.modules.paint.utils.bsdf_constants")
    const_mod.CHANNEL_TO_BSDF_SOCKET = {
        "Color": "Base Color",
        "Metallic": "Metallic",
        "Roughness": "Roughness",
        "Normal": "Normal",
    }
    const_mod.BSDF_COMPANION_PREFIXES = []
    const_mod.BSDF_COMPANION_SUFFIX_MAP = {}
    const_mod.CHANNEL_DEFAULT_VALUES = {}
    monkeypatch.setitem(sys.modules, "mixar.modules.paint.utils.bsdf_constants", const_mod)

    spec = importlib.util.spec_from_file_location(
        "mixar.modules.paint.core.io.utils.bsdf_connections", BSDF_PY
    )
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)
    spec.loader.exec_module(mod)
    return mod


def _build_material(*, base_color_source="none"):
    """Return (material, group_node). base_color_source in {none, group, mix, foreign}."""
    tree = _NodeTree()
    group = _Node("MP Group", type="GROUP")
    group.add_output("Color")
    group.add_output("Roughness")
    bsdf = _Node("Principled BSDF", type="BSDF_PRINCIPLED")
    base_color = bsdf.add_input("Base Color")
    roughness = bsdf.add_input("Roughness")
    bsdf.add_input("Metallic")
    tree.add_node(group)
    tree.add_node(bsdf)

    # The other mapped channels are always group-driven (as create_material wires
    # them), so each scenario varies only the Base Color source.
    tree.links.new(group.outputs.get("Roughness"), roughness)

    if base_color_source == "group":
        tree.links.new(group.outputs.get("Color"), base_color)
    elif base_color_source == "mix":
        # group.Color -> AO Multiply mix -> Base Color (create_material's AO chain)
        mix = _Node("AO Multiply", type="MIX")
        mix.add_input("A")
        mix_out = mix.add_output("Result")
        tree.add_node(mix)
        tree.links.new(group.outputs.get("Color"), mix.inputs.get("A"))
        tree.links.new(mix_out, base_color)
    elif base_color_source == "foreign":
        img = _Node("Image Texture", type="TEX_IMAGE")
        img_out = img.add_output("Color")
        tree.add_node(img)
        tree.links.new(img_out, base_color)
    # "none" -> leave Base Color unlinked
    return _Material(tree), group


# --------------------------------------------------------------------------- #
# bsdf_socket_driven_by_node
# --------------------------------------------------------------------------- #
def test_trace_direct_link(monkeypatch):
    m = _load_bsdf_module(monkeypatch)
    mat, group = _build_material(base_color_source="group")
    bsdf = m.find_principled_bsdf(mat)
    assert m.bsdf_socket_driven_by_node(bsdf, "Base Color", group) is True


def test_trace_via_intermediate(monkeypatch):
    m = _load_bsdf_module(monkeypatch)
    mat, group = _build_material(base_color_source="mix")
    bsdf = m.find_principled_bsdf(mat)
    assert m.bsdf_socket_driven_by_node(bsdf, "Base Color", group) is True


def test_trace_foreign_link_not_driven(monkeypatch):
    m = _load_bsdf_module(monkeypatch)
    mat, group = _build_material(base_color_source="foreign")
    bsdf = m.find_principled_bsdf(mat)
    assert m.bsdf_socket_driven_by_node(bsdf, "Base Color", group) is False


def test_trace_no_link_not_driven(monkeypatch):
    m = _load_bsdf_module(monkeypatch)
    mat, group = _build_material(base_color_source="none")
    bsdf = m.find_principled_bsdf(mat)
    assert m.bsdf_socket_driven_by_node(bsdf, "Base Color", group) is False


# --------------------------------------------------------------------------- #
# ensure_group_drives_bsdf
# --------------------------------------------------------------------------- #
def _base_color_link_from(mat):
    bsdf = None
    for node in mat.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            bsdf = node
    socket = bsdf.inputs.get("Base Color")
    return socket.links[0].from_node.name if socket.links else None


def test_relink_repairs_missing(monkeypatch):
    m = _load_bsdf_module(monkeypatch)
    mat, group = _build_material(base_color_source="none")
    relinked = m.ensure_group_drives_bsdf(mat, group)
    assert "Color" in relinked
    assert _base_color_link_from(mat) == "MP Group"


def test_relink_replaces_foreign(monkeypatch):
    m = _load_bsdf_module(monkeypatch)
    mat, group = _build_material(base_color_source="foreign")
    assert _base_color_link_from(mat) == "Image Texture"
    relinked = m.ensure_group_drives_bsdf(mat, group)
    assert "Color" in relinked
    assert _base_color_link_from(mat) == "MP Group"


def test_relink_leaves_direct_group_link(monkeypatch):
    m = _load_bsdf_module(monkeypatch)
    mat, group = _build_material(base_color_source="group")
    relinked = m.ensure_group_drives_bsdf(mat, group)
    assert relinked == []
    assert _base_color_link_from(mat) == "MP Group"


def test_relink_preserves_ao_multiply_chain(monkeypatch):
    """The AO-multiply chain (group->mix->BaseColor) is group-driven; do not bypass it."""
    m = _load_bsdf_module(monkeypatch)
    mat, group = _build_material(base_color_source="mix")
    relinked = m.ensure_group_drives_bsdf(mat, group)
    assert relinked == []
    # Base Color is still fed by the AO Multiply node, not directly by the group.
    assert _base_color_link_from(mat) == "AO Multiply"


# --------------------------------------------------------------------------- #
# _enabled_layers_above_base (index 0 == TOP)
# --------------------------------------------------------------------------- #
def _load_common(monkeypatch):
    fake_bpy = types.SimpleNamespace(
        context=types.SimpleNamespace(
            selected_objects=[], active_object=None,
            scene=types.SimpleNamespace(objects=[]),
        ),
        data=types.SimpleNamespace(objects=types.SimpleNamespace(get=lambda n: None)),
    )
    monkeypatch.setitem(sys.modules, "bpy", fake_bpy)
    for name in ("mixar", "mixar.config", "mixar.modules", "mixar.modules.paint",
                 "mixar.modules.paint.utils"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    log_mod = types.ModuleType("mixar.config.logging_config")
    log_mod.get_logger = lambda *a, **k: MagicMock()
    monkeypatch.setitem(sys.modules, "mixar.config.logging_config", log_mod)
    const_mod = types.ModuleType("mixar.modules.paint.utils.constants")
    const_mod.MP_GROUP_PREFIX = "MP_"
    monkeypatch.setitem(sys.modules, "mixar.modules.paint.utils.constants", const_mod)

    spec = importlib.util.spec_from_file_location("agent_tools_common_link_test", COMMON_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _layer(name, enable=True, pid=""):
    return types.SimpleNamespace(name=name, enable=enable, procedural_material_id=pid)


def test_layers_above_base_reports_top_layers(monkeypatch):
    common = _load_common(monkeypatch)
    # index 0 == TOP; base at index 2, so indices 0 and 1 are "above".
    mp = types.SimpleNamespace(layers=[
        _layer("Leftover Fill"), _layer("Detail"), _layer("PBR Base"),
    ])
    above = common._enabled_layers_above_base(mp, "", "PBR Base")
    assert above == ["Leftover Fill", "Detail"]


def test_layers_above_base_skips_disabled(monkeypatch):
    common = _load_common(monkeypatch)
    mp = types.SimpleNamespace(layers=[
        _layer("Hidden", enable=False), _layer("PBR Base"),
    ])
    assert common._enabled_layers_above_base(mp, "", "PBR Base") == []


def test_layers_above_base_none_when_base_missing(monkeypatch):
    common = _load_common(monkeypatch)
    mp = types.SimpleNamespace(layers=[_layer("A"), _layer("B")])
    assert common._enabled_layers_above_base(mp, "", "Nonexistent") == []
