# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Reachability contracts for the Flora-style moodboard inference graph.

Native drawing and hit-testing require the compiled Mixie editor, so these
standalone checks pin the registration and Python/C++ seams that make the
feature reachable in-app.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_graph_records_are_persistent_scene_properties_and_unregister_cleanly():
    registration = _read(MOODBOARD / "ui/moodboard_scene_registration.py")
    properties = _read(MOODBOARD / "ui/moodboard_graph_properties.py")
    media_properties = _read(MOODBOARD / "ui/moodboard_properties.py")

    for name in (
        "mixie_moodboard_action_nodes",
        "mixie_moodboard_asset_nodes",
        "mixie_moodboard_links",
    ):
        assert registration.count(f"'{name}'") >= 2
    assert "node_id: StringProperty" in media_properties
    assert "embedded_node_id: StringProperty" in media_properties
    assert "class MixieMoodboardNodeParameter" in properties
    assert "class MixieMoodboardActionNode" in properties
    assert "class MixieMoodboardAssetNode" in properties
    assert "class MixieMoodboardLink" in properties


def test_native_graph_renderer_and_operators_are_compiled_and_registered():
    cmake = _read(SPACE_MIXIE / "CMakeLists.txt")
    space = _read(SPACE_MIXIE / "space_mixie.cc")
    canvas = _read(SPACE_MIXIE / "mixie_draw_moodboard.cc")
    renderer = _read(SPACE_MIXIE / "mixie_draw_moodboard_graph.cc")
    controls = _read(SPACE_MIXIE / "mixie_draw_moodboard_node_ui.cc")

    assert "mixie_draw_moodboard_graph.cc" in cmake
    assert "mixie_draw_moodboard_node_ui.cc" in cmake
    assert "mixie_moodboard_ops_graph.cc" in cmake
    assert "MIXIE_OT_moodboard_graph_select" in space
    assert "MIXIE_OT_moodboard_context_menu" in space
    assert "mixie_draw_moodboard_links" in canvas
    geometry = _read(SPACE_MIXIE / "mixie_moodboard_graph_geometry.cc")
    assert "BKE_curve_forward_diff_bezier" in geometry
    assert "mixie_draw_moodboard_graph_controls" in renderer
    assert '"prompt",' in controls
    # Mode/Model draw the Python-cached human labels (dynamic enums can't
    # self-display); the static word is only the empty-label fallback.
    assert 'model_label[0] ? model_label : "Model"' in controls
    assert 'mode_label[0] ? mode_label : "Mode"' in controls
    assert "BLI_rcti_size_x(&node_region) < MOODBOARD_GRAPH_CONTROLS_MIN_PX_X" in controls
    # The draft hint draws exactly when the floating controls do not, so both
    # sides must share the same on-screen size thresholds.
    assert "MOODBOARD_GRAPH_CONTROLS_MIN_PX_X" in renderer
    assert "draw_draft_hint" in renderer
    assert "draw_state_hint" in renderer
    assert 'mixie_rna_string_get_clamped(node, "prompt"' in renderer
    assert "generation_running" in controls
    assert 'RNA_boolean_get(&iter.ptr, "visible")' in controls
    # Numeric parameters are plain manual number fields: the catalog's wide
    # min/max ranges made drag-sliders unusable (e.g. Duration max 3000).
    assert 'STREQ(widget, "slider")' not in controls
    assert "button_type = ButType::Num;" in controls
    assert 'RNA_struct_find_property(node, "parameters")' in controls
    assert "uiDefButO" in controls
    assert '"MIXIE_OT_moodboard_run_action_node"' in controls
    assert controls.index("UI_view2d_view_restore(C)") < controls.index(
        "UI_block_begin("
    )
    assert "UI_region_handlers_add" in space
    assert "ED_KEYMAP_UI | ED_KEYMAP_GIZMO" in space
    assert "moodboard_action_run_button_rect" not in renderer
    assert "UI_draw_roundbox_4fv" in renderer


def test_context_actions_create_connected_nodes_and_execute_through_queue():
    menu = _read(MOODBOARD / "ui/moodboard_menus.py")
    graph = _read(MOODBOARD / "core/node_graph.py")
    execution = _read(MOODBOARD / "core/node_execution.py")
    enqueue = _read(
        ROOT / "src/scripts/mixar/modules/common/job_queue/core/enqueue.py"
    )

    assert "'IMAGE_GEN', \"Generate Image\"" in menu
    assert "'MODEL_3D', \"Generate to 3D\"" in menu
    assert '_capability_available("video_gen")' in menu
    assert "add_link(" in graph
    assert "connect_to_next_input(" in graph
    assert "graph_node_id=node.node_id" in execution
    assert "on_imported=hook" in execution
    assert "_on_imported_hook=on_imported" in enqueue


def test_catalog_schema_and_results_stay_inside_reusable_blocks():
    schema = _read(MOODBOARD / "core/node_schema.py")
    graph = _read(MOODBOARD / "core/node_graph.py")
    execution = _read(MOODBOARD / "core/node_execution.py")
    properties = _read(MOODBOARD / "ui/moodboard_graph_properties.py")
    catalog = _read(ROOT / "src/scripts/mixar/bootstrap/generation_catalog_cache.py")

    assert "def sync_node_schema" in schema
    assert "def collect_node_params" in schema
    assert "def refresh_node_parameter_visibility" in schema
    assert "def sync_all_node_schemas" in schema
    assert 'get_services(capability, surface="moodboard")' in graph
    assert "sync_all_node_schemas()" in catalog
    assert "parameters: CollectionProperty" in properties
    assert "visible: BoolProperty" in properties
    assert "show_mode: BoolProperty" in properties
    assert "preview_image: PointerProperty" in properties
    assert "preview_object: PointerProperty" in properties
    assert "def connect_image_result" in graph
    assert "float(node.width) * aspect" in schema
    assert "capability_for_action(node.action_type)" in graph
    assert "item.embedded_node_id = action_node.node_id" in graph
    assert "collect_node_params(node)" in execution
    assert 'kind="image"' in execution


def test_queue_state_bridge_targets_originating_scene_and_node():
    bridge = _read(MOODBOARD / "core/node_job_bridge.py")
    job = _read(ROOT / "src/scripts/mixar/modules/common/job_queue/core/job.py")

    assert "graph_node_id: str" in job
    assert 'bpy.data.scenes.get(getattr(job, "scene_name", ""))' in bridge
    assert "action_node_by_id(scene, node_id)" in bridge
    assert "JobState.SUCCESS" in bridge
    assert "JobState.FAILED" in bridge
