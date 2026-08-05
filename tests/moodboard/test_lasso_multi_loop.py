# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Contracts for multi-loop lasso capture and progressive SAM3 refinement."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"


def test_lasso_pipeline_submits_loops_sequentially_and_adds_each_result():
    source = (MOODBOARD / "ui/operators/lasso_select_sam_ops.py").read_text()
    mask_tool = (MOODBOARD / "ui/operators/moodboard_mask_ops.py").read_text()

    assert "lasso_loops" in source
    assert "_perform_mask_segmentations" in source
    assert "_create_segment_from_mask(" in source
    assert "Continue only after the current result is visible" in source
    assert "Draw another loop or press Enter" in mask_tool
    assert "return {'RUNNING_MODAL'}" in mask_tool


def test_lasso_segments_keep_the_source_image_visible():
    source = (MOODBOARD / "ui/operators/lasso_select_sam_ops.py").read_text()
    overlay = (MOODBOARD / "core/segment_overlay.py").read_text()

    assert "segment.show_overlay = True" in source
    assert "segment.outline_only = True" in source
    assert "segment.selection_outline = json.dumps" in source
    assert 'getattr(segment, "show_overlay", True)' in overlay
    assert 'getattr(segment, "outline_only", False)' in overlay
    assert "_original_lasso_edge" in overlay


def test_debug_mode_adds_raw_sam3_mask_preview():
    source = (MOODBOARD / "ui/operators/lasso_select_sam_ops.py").read_text()
    debug = (MOODBOARD / "core/component_debug.py").read_text()

    assert "add_sam3_mask_preview" in source
    assert 'config.get("log_level", "INFO")' in debug
    assert 'preview.component_role = \'DEBUG_MASK\'' in debug
