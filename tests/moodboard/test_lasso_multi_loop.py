# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Contracts for multi-loop lasso capture and progressive SAM3 refinement."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"


def test_lasso_pipeline_submits_loops_sequentially_and_adds_each_result():
    source = (MOODBOARD / "ui/operators/lasso_select_sam_ops.py").read_text(encoding="utf-8")
    mask_tool = (MOODBOARD / "ui/operators/moodboard_mask_ops.py").read_text(encoding="utf-8")

    assert "lasso_loops" in source
    assert "_perform_mask_segmentations" in source
    assert "_create_segment_from_mask(" in source
    assert "Continue only after the current result is visible" in source
    assert "Draw another loop or press Enter" in mask_tool
    assert "return {'RUNNING_MODAL'}" in mask_tool


def test_lasso_segments_keep_the_source_image_visible():
    source = (MOODBOARD / "ui/operators/lasso_select_sam_ops.py").read_text(encoding="utf-8")
    overlay = (MOODBOARD / "core/segment_overlay.py").read_text(encoding="utf-8")

    assert "segment.show_overlay = True" in source
    assert "segment.outline_only = True" in source
    assert "segment.selection_outline = json.dumps" in source
    assert 'getattr(segment, "show_overlay", True)' in overlay
    assert 'getattr(segment, "outline_only", False)' in overlay
    assert "_original_lasso_edge" in overlay


def test_debug_mode_adds_raw_sam3_mask_preview():
    source = (MOODBOARD / "ui/operators/lasso_select_sam_ops.py").read_text(encoding="utf-8")
    debug = (MOODBOARD / "core/component_debug.py").read_text(encoding="utf-8")

    assert "add_sam3_mask_preview" in source
    assert 'config.get("log_level", "INFO")' in debug
    assert 'preview.component_role = \'DEBUG_MASK\'' in debug


def test_debug_preview_snapshots_source_before_collection_growth():
    """Never dereference a CollectionProperty item after adding a sibling."""
    debug = (MOODBOARD / "core/component_debug.py").read_text(encoding="utf-8")
    add_index = debug.index("preview = scene.mixie_moodboard_images.add()")
    before_add = debug[:add_index]
    after_add = debug[add_index:debug.index("return preview", add_index)]

    assert "source_scale = source.scale" in before_add
    assert "source_position_x = source.position_x" in before_add
    assert "source_position_y = source.position_y" in before_add
    assert "source.image" in before_add
    assert "source." not in after_add
