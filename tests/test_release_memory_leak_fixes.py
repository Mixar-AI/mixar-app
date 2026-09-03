# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "scripts" / "mixar" / "modules"


def read_src(relative_path: str) -> str:
    return (SRC / relative_path).read_text(encoding="utf-8")


def test_uv_editor_unregister_uses_timer_is_registered():
    source = read_src("uv_editor/ui/properties_handlers.py")

    assert "bpy.app.timers.is_registered(_check_tool_and_refresh)" in source
    assert "if _check_tool_and_refresh in bpy.app.timers" not in source


def test_mixie_chat_unregisters_slot_property_classes():
    source = read_src("space_mixie_chat/ui/properties/chat_props.py")

    assert "from .chat_slot_types import classes as slot_classes" in source
    assert "for cls in reversed(slot_classes):" in source


def test_scene_gen_clear_all_clears_all_job_state_maps():
    source = read_src("moodboard/core/scene_gen_manager.py")

    for attr in (
        "_download_attempts",
        "_failed_objects",
        "_error_callbacks",
    ):
        assert f"self.{attr}.clear()" in source


def test_scene_segment_completed_requests_are_pruned():
    source = read_src("moodboard/core/scene_segment_requests.py")

    assert "state.requests.pop(request.request_id, None)" in source
    assert "state.requests.pop(request_id, None)" in source
    assert "request.callback = None" in source


def test_dither_early_returns_recover_composite_settings():
    source = read_src("paint/ui/bake/utils/compositor_effects.py")
    tree = ast.parse(source)
    dither = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "dither_image"
    )

    prepare_line = next(
        node.lineno for node in ast.walk(dither)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "prepare_composite_settings"
    )
    recover_lines = [
        node.lineno for node in ast.walk(dither)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "recover_composite_settings"
    ]

    for node in ast.walk(dither):
        if isinstance(node, ast.Return) and node.lineno > prepare_line:
            assert any(line < node.lineno for line in recover_lines)


def test_lookdev_failed_depth_render_cleans_temp_compositor():
    source = read_src("moodboard/core/lookdev_utils.py")

    failure_block_start = source.index('logger.error("[Lookdev] Failed to save depth render")')
    failure_block = source[failure_block_start:source.index("logger.debug(\"[Lookdev] Depth render saved\")")]

    assert "_restore_render_settings(" in failure_block
    assert "_cleanup_temp_compositor(node_tree)" in failure_block


def test_chat_file_image_datablocks_are_cleaned_when_records_are_removed():
    image_ops = read_src("space_mixie_chat/ui/operators/image_ops.py")
    chat_api_ops = read_src("space_mixie_chat/ui/operators/chat_api_ops.py")
    screenshot_ops = read_src("space_mixie_chat/ui/operators/screenshot_ops.py")

    assert "cleanup_loaded_file_image(image_path)" in image_ops
    assert "cleanup_loaded_file_images(paths)" in image_ops
    assert "cleanup_loaded_file_images(paths)" in chat_api_ops
    assert "collect_message_file_image_paths(messages[self.index])" in chat_api_ops
    assert "cleanup_loaded_file_image(att.image_path)" in screenshot_ops
