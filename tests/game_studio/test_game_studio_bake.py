# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Material baking for the game GLB: which materials need a bake
(``bake_plan``), the background job around it (``bake_job``), chunking and
the cache (``bake_run``), and the launch path that keeps the user's session
free."""

import json
import os
import types
from pathlib import Path

import pytest

from mixar.modules.game_studio.constants import ROLE_PROP
from mixar.modules.game_studio.core import bake_plan, visuals

MODULE = Path(__file__).parents[2] / "src/scripts/mixar/modules/game_studio"


class Sockets(list):
    def get(self, name, default=None):
        return next((s for s in self if s.name == name), default)


class Node:
    def __init__(self, type_, name=None, inputs=(), outputs=("Out",), node_tree=None, image=None):
        self.type, self.name, self.node_tree, self.image = type_, name or type_, node_tree, image
        self.inputs = Sockets(types.SimpleNamespace(name=n, identifier=n, links=[], is_linked=False,
                                                    default_value=1.0) for n in inputs)
        self.outputs = Sockets(types.SimpleNamespace(name=n, identifier=n) for n in outputs)


def link(from_node, out, to_node, inp):
    socket = to_node.inputs.get(inp)
    socket.links.append(types.SimpleNamespace(from_node=from_node, from_socket=from_node.outputs.get(out)))
    socket.is_linked = True


def material(name, wire):
    """A Principled material; ``wire(bsdf)`` adds its upstream graph."""
    bsdf = Node("BSDF_PRINCIPLED", inputs=("Base Color", "Roughness", "Metallic", "Normal", "Emission Color",
                                           "Emission Strength", "Alpha"), outputs=("BSDF",))
    out = Node("OUTPUT_MATERIAL", inputs=("Surface", "Volume"))
    out.is_active_output = True
    link(bsdf, "BSDF", out, "Surface")
    nodes = [out, bsdf] + list(wire(bsdf) or ())
    return types.SimpleNamespace(name=name, node_tree=types.SimpleNamespace(nodes=nodes, links=[]))


def image_node():
    return Node("TEX_IMAGE", inputs=("Vector",), outputs=("Color", "Alpha"), image=object())


def plain_image(bsdf):
    tex = image_node()
    link(tex, "Color", bsdf, "Base Color")
    normal_tex, normal_map = image_node(), Node("NORMAL_MAP", inputs=("Color",), outputs=("Normal",))
    link(normal_tex, "Color", normal_map, "Color")
    link(normal_map, "Normal", bsdf, "Normal")
    return [tex, normal_tex, normal_map]


def grime(bsdf):
    tex, noise, mix = image_node(), Node("TEX_NOISE", inputs=("Vector",), outputs=("Fac", "Color")), \
        Node("MIX", inputs=("Factor", "A", "B"), outputs=("Result",))
    link(tex, "Color", mix, "A")
    link(noise, "Fac", mix, "Factor")
    link(mix, "Result", bsdf, "Base Color")
    return [tex, noise, mix]


def procedural_in_group(bsdf):
    noise = Node("TEX_NOISE", outputs=("Fac",))
    group_out = Node("GROUP_OUTPUT", inputs=("Value",))
    link(noise, "Fac", group_out, "Value")
    group = Node("GROUP", outputs=("Value",), node_tree=types.SimpleNamespace(nodes=[noise, group_out]))
    link(group, "Value", bsdf, "Roughness")
    return [group]


def object_info(bsdf):
    info, ramp = Node("OBJECT_INFO", outputs=("Random",)), Node("VALTORGB", inputs=("Fac",), outputs=("Color",))
    link(info, "Random", ramp, "Fac")
    link(ramp, "Color", bsdf, "Base Color")
    return [info, ramp]


@pytest.fixture(autouse=True)
def _fresh_caches():
    visuals.clear_caches()
    yield
    visuals.clear_caches()


@pytest.mark.parametrize("wire,needs,reasons,relative", [
    (lambda b: None, False, [], False),                      # constants only
    (plain_image, False, [], False),                         # image + normal map: glTF carries it
    (grime, True, ["Base Color"], False),                    # Mixie's grime over an image
    (procedural_in_group, True, ["Roughness"], False),       # procedural hidden in a group
    (object_info, True, ["Base Color"], True),               # per-object colour: bake in place
])
def test_material_verdicts(wire, needs, reasons, relative):
    verdict = bake_plan.material_verdict(material("M", wire))
    assert (verdict["needs"], verdict["reasons"], verdict["object_relative"]) == (needs, reasons, relative)


def test_masked_emission_strength_alone_is_left_to_the_lane():
    def mask(bsdf):
        tex, math = image_node(), Node("MATH", inputs=("Value", "Value_001"), outputs=("Value",))
        link(tex, "Color", math, "Value")
        link(math, "Value", bsdf, "Emission Strength")
        return [tex, math]
    assert bake_plan.material_verdict(material("Lava", mask))["needs"] is False


def test_non_principled_surfaces_are_reported_not_baked():
    shader = material("Mixed", lambda b: None)
    out = shader.node_tree.nodes[0]
    mix = Node("MIX_SHADER", outputs=("Shader",))
    out.inputs.get("Surface").links = [types.SimpleNamespace(from_node=mix, from_socket=mix.outputs.get("Shader"))]
    verdict = bake_plan.material_verdict(shader)
    assert verdict["unsupported"] and not verdict["needs"]


def _mesh(make_obj, name, *mats, parent=None):
    obj = make_obj(name, "MESH", parent=parent)
    obj.data = types.SimpleNamespace(name=f"{name}_data", materials=list(mats))
    return obj


def test_plan_skips_characters_and_dedupes_instances(make_obj):
    dirty, clean = material("Grime", grime), material("Clean", plain_image)
    boss = make_obj("boss_character_Root", "EMPTY")
    boss[ROLE_PROP] = "boss"
    staff = _mesh(make_obj, "Staff", dirty, parent=make_obj("Grip", "EMPTY", parent=boss))
    wall_a = _mesh(make_obj, "Wall_A", dirty, clean)
    wall_b = _mesh(make_obj, "Wall_B", clean)
    rock_1 = _mesh(make_obj, "Rock.001", dirty)
    rock_2 = _mesh(make_obj, "Rock.002", dirty)
    rock_2.data = rock_1.data  # an instance
    planned = bake_plan.plan([staff, wall_a, wall_b, rock_1, rock_2])
    assert planned["materials"] == ["Grime"]
    assert [o.name for o in planned["meshes"]] == ["Rock.001", "Wall_A"]
    assert planned["character_materials"] == []  # Grime is baked elsewhere, so it is not "character only"
    only_boss = bake_plan.plan([staff])
    assert only_boss["meshes"] == [] and only_boss["character_materials"] == ["Grime"]


# --- chunking and the cache ------------------------------------------------------

def test_resolution_and_chunks(monkeypatch):
    from mixar.modules.game_studio.core import bake_run
    assert bake_run.resolution(0.01, 128) == 512 and bake_run.resolution(10_000, 128) == 2048
    assert bake_run.resolution(4.0, 128) == 512 and bake_run.resolution(40.0, 128) == 2048
    areas = {"a": 30.0, "b": 50.0, "c": 40.0, "d": 3000.0}
    monkeypatch.setattr(bake_run, "world_area", lambda obj: areas[obj.name])
    objs = [types.SimpleNamespace(name=n) for n in areas]
    chunks = bake_run.make_chunks(objs)
    assert [[o.name for o in c["meshes"]] for c in chunks][0][0] == "a"
    assert sum(c["res"] ** 2 for c in chunks) <= bake_run.TOTAL_PIXELS
    assert all(bake_run.MIN_RES <= c["res"] <= bake_run.MAX_RES for c in chunks)


def test_cache_entries_are_written_atomically(tmp_path, monkeypatch):
    from mixar.modules.game_studio.core import bake_run
    source = tmp_path / "color.jpg"
    source.write_bytes(b"jpg")
    entry = bake_run.write_entry(str(tmp_path / "cache"), "k1", {"color.jpg": str(source)},
                                 {"Wall_data": [0.0, 1.0]}, {"res": 512})
    assert bake_run.cache_entry(str(tmp_path / "cache"), "k1") == entry
    assert json.loads(Path(entry, "meta.json").read_text()) == {"res": 512}
    monkeypatch.setattr(bake_run.np, "savez_compressed", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        bake_run.write_entry(str(tmp_path / "cache"), "k2", {"color.jpg": str(source)}, {}, {})
    assert bake_run.cache_entry(str(tmp_path / "cache"), "k2") is None
    assert not [p for p in os.listdir(tmp_path / "cache") if p.startswith(".tmp")]


# --- the background job ------------------------------------------------------------

class _Handle:
    def __init__(self):
        import threading
        self.job_id, self.cancel_event, self.reports = "j", threading.Event(), []

    @property
    def cancelled(self):
        return self.cancel_event.is_set()

    def progress(self, pct, message=None, force=False):
        self.reports.append((round(pct, 1), message))


def test_stage_runs_the_child_and_always_discards_the_copy(tmp_path):
    from mixar.modules.game_studio.core import bake_job
    folder = tmp_path / "bake" / "x"
    folder.mkdir(parents=True)
    bake = {"folder": str(folder), "copy": str(folder / "scene.mixar"), "config": str(folder / "c.json"),
            "binary": "/Mixar", "result": str(folder / "r.json")}
    seen = {}

    def runner(binary, args, result, action, on_progress=None, cancel=None, timeout=0, schema=""):
        seen.update(binary=binary, args=args, schema=schema, timeout=timeout)
        on_progress(50.0, "bake", "Baking color (2048 px)")
        return {"ok": True, "bake": {"materials": ["Grime"]}, "package": {"warnings": ["w"]}}

    handle = _Handle()
    result = bake_job.stage(bake, handle, 0.0, 50.0, runner=runner)
    assert result["bake"]["materials"] == ["Grime"] and not folder.exists()
    assert seen["args"][:4] == ["-b", bake["copy"], "-noaudio", "--python"]
    assert seen["args"][4].endswith("bake_child.py") and seen["args"][-2:] == ["--mixar-bake", bake["config"]]
    assert seen["schema"] == "mixar_bake_result_v1" and (25.0, "Baking color (2048 px)") in handle.reports

    folder.mkdir(parents=True)
    from mixar.modules.game_studio.core.jobs import JobError
    with pytest.raises(JobError) as failed:
        bake_job.stage(bake, _Handle(), runner=lambda *a, **k: {"ok": False, "error_code": "timeout"})
    assert failed.value.code == "timeout" and "too long" in failed.value.message and not folder.exists()


def test_with_bake_scales_the_godot_work_after_the_bake(monkeypatch):
    from mixar.modules.game_studio.core import bake_job
    monkeypatch.setattr(bake_job, "stage", lambda bake, handle, low, high: (
        handle.progress(high, "Baked"), {"bake": {"chunks": 4}, "package": {"warnings": ["baked w"]}})[1])

    def godot_work(handle):
        handle.progress(50.0, "Building the Godot project")
        return {"project_dir": "p", "warnings": ["godot w"]}

    handle = _Handle()
    outcome = bake_job.with_bake({}, godot_work)(handle)
    assert outcome["bake"] == {"chunks": 4} and outcome["warnings"] == ["godot w", "baked w"]
    assert (77.5, "Building the Godot project") in handle.reports


# --- source pins ---------------------------------------------------------------------

def test_launch_bakes_off_the_main_thread_only_when_needed():
    source = (MODULE / "core/launch.py").read_text(encoding="utf-8")
    body = source[source.index("def _run("):source.index("def _run_baked(")]
    assert body.index('if checked["bake_materials"]:') < body.index("exporter.write_package(scene)")
    baked = source[source.index("def _run_baked("):source.index("def start(")]
    assert "bake_job.prepare(scene, game_dir)" in baked and "write_package" not in baked
    assert "bake_job.with_bake(bake, make_work(" in baked
    prepare = (MODULE / "core/bake_job.py").read_text(encoding="utf-8")
    assert "keep_windows_for_snapshot" in prepare and "copy=True, thumbnail=False" in prepare


def test_bake_modules_are_denied_to_agent_scripts():
    from mixar.modules.space_mixie_chat.core.sandbox_modules import is_denied_module
    for name in ("bake_job", "bake_run", "bake_passes", "bake_child"):
        assert is_denied_module(f"mixar.modules.game_studio.core.{name}")
    assert not is_denied_module("mixar.modules.game_studio.core.bake_plan")
    plan = (MODULE / "core/bake_plan.py").read_text(encoding="utf-8")
    for banned in ("open(", "import bpy", "subprocess"):
        assert banned not in plan


def test_bake_setting_never_reaches_the_fork():
    from mixar.modules.game_studio.core import spec
    merged, errors = spec.merge_settings(spec.DEFAULT_SETTINGS, {"bake_materials": False})
    assert errors == [] and merged["bake_materials"] is False
    assert spec.merge_settings(spec.DEFAULT_SETTINGS, {"bake_materials": "yes"})[1]
    assert "bake_materials" not in spec.build_spec(merged, [])
