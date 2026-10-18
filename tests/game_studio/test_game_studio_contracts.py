# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Source-level contracts: the single GLB lane with extras OFF, the sandbox
boundary around the agent API, module layout and size."""

import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]
MODULE = ROOT / "src/scripts/mixar/modules/game_studio"
CHAT_CORE = ROOT / "src/scripts/mixar/modules/space_mixie_chat/core"


def _calls(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            yield node


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def test_exporter_uses_the_shared_lane_only():
    source = (MODULE / "core/exporter.py").read_text(encoding="utf-8")
    assert "from mixar.modules.space_mixie_chat.core.agent_export import export_to_path" in source
    assert any(_dotted(call.func) == "export_to_path" for call in _calls(MODULE / "core/exporter.py"))
    for path in MODULE.rglob("*.py"):
        for call in _calls(path):
            name = _dotted(call.func)
            assert not name.endswith("export_scene.gltf"), f"{path} calls {name}"
            for keyword in call.keywords:
                assert keyword.arg != "export_extras", f"{path} passes export_extras"


def test_game_preset_keeps_extras_off_and_scene_scoped():
    tree = ast.parse((CHAT_CORE / "export_presets.py").read_text(encoding="utf-8"))
    game = next(node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                and any(getattr(t, "id", "") == "_GLTF_GAME" for t in node.targets))
    entries = {key.value: value for key, value in zip(game.value.keys, game.value.values) if key is not None}
    assert entries["export_extras"].value is False
    assert entries["export_cameras"].value is False and entries["export_lights"].value is False
    from mixar.modules.space_mixie_chat.core import export_presets
    kwargs = export_presets.preset_kwargs("game", "glb")
    assert kwargs["export_extras"] is False and kwargs["use_active_scene"] is True
    assert kwargs["export_apply"] is True and kwargs["use_selection"] is True
    assert "game" in export_presets.USE_CASES


def test_export_to_path_reuses_run_export_and_stages_game_markers():
    source = (CHAT_CORE / "agent_export.py").read_text(encoding="utf-8")
    body = source[source.index("def export_to_path"):source.index("def inspect_export")]
    assert "run_export(session" in body and "clear_destination(session)" in body
    assert "is_game_gltf(use_case, fmt)" in source
    assert "game_scene_objects(meshes, spec.get(\"extra_object_names\"), scene)" in source


def test_game_scene_objects_stage_markers_and_ancestors():
    class NS:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    from mixar.modules.space_mixie_chat.core.export_web import game_scene_objects
    root = NS(name="Level", type="EMPTY", parent=None)
    mesh = NS(name="Hero", type="MESH", parent=root)
    spawn = NS(name="Spawn", type="EMPTY", parent=None)
    lamp = NS(name="Lamp", type="LIGHT", parent=None)
    scene = NS(objects=[root, mesh, spawn, lamp])
    staged = game_scene_objects([mesh], ["Spawn", "Lamp", "Missing"], scene)
    assert staged == {root, spawn}


def test_agent_api_holds_no_process_or_path_capable_module():
    tree = ast.parse((MODULE / "core/agent_api.py").read_text(encoding="utf-8"))
    denied = {"godot_locator", "godot_runner", "exporter", "jobs", "pipeline", "store_client"}
    for node in tree.body:  # module level only: lazy imports live inside functions
        if isinstance(node, ast.ImportFrom):
            names = {alias.name for alias in node.names}
            assert not names & denied, names
            assert not (node.module or "").split(".")[-1] in denied
        assert not isinstance(node, ast.Import) or all(a.name in ("json", "os", "bpy") for a in node.names)


def test_sandbox_denies_game_internals_but_not_the_agent_api():
    from mixar.modules.space_mixie_chat.core.sandbox_modules import is_denied_module
    base = "mixar.modules.game_studio.core."
    for name in ("godot_locator", "godot_runner", "exporter", "jobs", "pipeline", "store_client"):
        assert is_denied_module(base + name)
    for name in ("agent_api", "roles", "spec"):
        assert not is_denied_module(base + name)


def test_layout_and_size_rules():
    assert (MODULE / "constants.py").is_file()
    for path in MODULE.rglob("*.py"):
        lines = path.read_text(encoding="utf-8").count("\n")
        assert lines <= 500, f"{path} has {lines} lines"
    props = (MODULE / "ui/properties/game_props.py").read_text(encoding="utf-8")
    ops = (MODULE / "ui/operators/game_ops.py").read_text(encoding="utf-8")
    panels = (MODULE / "ui/panels/game_panels.py").read_text(encoding="utf-8")
    assert "(Operator)" not in props and "(PropertyGroup)" not in ops
    for source in (props, ops, panels):
        assert "\nclasses = (" in source
    assert 'bl_category = "Game"' in panels


def test_ui_draw_does_no_blocking_work():
    panels = (MODULE / "ui/panels/game_panels.py").read_text(encoding="utf-8")
    for banned in ("subprocess", "requests", "locate(", "write_package", "agent_api"):
        assert banned not in panels


def test_combat_and_characters_stay_pure_for_agent_scripts():
    # Agent scripts reach these through ``spec``; file reads live in exporter.
    for name in ("combat", "characters"):
        source = (MODULE / f"core/{name}.py").read_text(encoding="utf-8")
        for banned in ("open(", "import bpy", "import os", "subprocess"):
            assert banned not in source, f"{name}.py uses {banned}"
    assert "def read_timeline" in (MODULE / "core/exporter.py").read_text(encoding="utf-8")


def test_combat_panel_is_boss_fight_only_and_reads_the_shared_check():
    panels = (MODULE / "ui/panels/game_panels.py").read_text(encoding="utf-8")
    body = panels[panels.index("class MIXAR_PT_game_combat"):panels.index("class MIXAR_PT_game_publish")]
    assert "return context.window_manager.mixar_game.template == BOSS_TEMPLATE" in body
    assert "bl_parent_id" not in body and "DEFAULT_CLOSED" not in body  # open where it shows
    assert "checked_scene(context.scene)" in body and "inspect(" not in body
    checks = panels[panels.index("def _draw_checks"):panels.index("def _draw_last")]
    assert "checked_scene(context.scene)" in checks
    tuple_src = panels[panels.index("\nclasses = ("):]
    assert tuple_src.index("MIXAR_PT_game_settings") < tuple_src.index("MIXAR_PT_game_combat")


def test_ui_lists_the_v13_choices():
    props = (MODULE / "ui/properties/game_props.py").read_text(encoding="utf-8")
    for key in ('("boss", "Boss"', '("boss_fight", "Boss Fight"', '("defeat_boss", "Defeat Boss"',
                "boss_hp: IntProperty("):
        assert key in props
