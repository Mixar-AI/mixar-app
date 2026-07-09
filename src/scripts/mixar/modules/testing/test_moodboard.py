# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for moodboard module.

Tests moodboard constants and lookdev_utils.calculate_optimal_depth_resolution().
Moodboard_utils functions that require bpy context are tested via mocks.
"""

# Install bpy mock before any mixar imports
import sys, os
_test_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.abspath(os.path.join(_test_dir, "..", "..", ".."))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
try:
    import bpy
except ImportError:
    import importlib.util
    _mock_spec = importlib.util.spec_from_file_location(
        "mock_bpy", os.path.join(_test_dir, "mock_bpy.py"))
    _mock_mod = importlib.util.module_from_spec(_mock_spec)
    _mock_spec.loader.exec_module(_mock_mod)

import unittest
from unittest.mock import MagicMock


class TestMoodboardConstants(unittest.TestCase):
    """Tests for moodboard.constants configuration values."""

    def test_image_base_size(self):
        from mixar.modules.moodboard.constants import MOODBOARD_IMAGE_BASE_SIZE
        self.assertEqual(MOODBOARD_IMAGE_BASE_SIZE, 700.0)

    def test_image_scale_range(self):
        from mixar.modules.moodboard.constants import IMAGE_SCALE_MIN, IMAGE_SCALE_MAX
        self.assertGreater(IMAGE_SCALE_MIN, 0)
        self.assertGreater(IMAGE_SCALE_MAX, IMAGE_SCALE_MIN)

    def test_rotation_range(self):
        from mixar.modules.moodboard.constants import IMAGE_ROTATION_MIN, IMAGE_ROTATION_MAX
        self.assertEqual(IMAGE_ROTATION_MIN, -360.0)
        self.assertEqual(IMAGE_ROTATION_MAX, 360.0)

    def test_textbox_defaults(self):
        from mixar.modules.moodboard.constants import (
            TEXTBOX_TEXT_DEFAULT, TEXTBOX_FONT_SIZE_DEFAULT,
            TEXTBOX_FONT_SIZE_MIN, TEXTBOX_FONT_SIZE_MAX,
        )
        self.assertEqual(TEXTBOX_TEXT_DEFAULT, "Text")
        self.assertGreater(TEXTBOX_FONT_SIZE_DEFAULT, TEXTBOX_FONT_SIZE_MIN)
        self.assertLess(TEXTBOX_FONT_SIZE_DEFAULT, TEXTBOX_FONT_SIZE_MAX)

    def test_gemini_models(self):
        from mixar.modules.moodboard.constants import GEMINI_MODELS
        self.assertGreaterEqual(len(GEMINI_MODELS), 2)
        # Each model is a tuple of (id, label, description)
        for model in GEMINI_MODELS:
            self.assertEqual(len(model), 3)
            self.assertIsInstance(model[0], str)

    def test_aspect_ratios(self):
        from mixar.modules.moodboard.constants import ASPECT_RATIOS
        ratio_ids = [r[0] for r in ASPECT_RATIOS]
        self.assertIn('1:1', ratio_ids)
        self.assertIn('16:9', ratio_ids)
        self.assertIn('9:16', ratio_ids)

    def test_edit_tool_types(self):
        from mixar.modules.moodboard.constants import EDIT_TOOL_TYPES
        tool_ids = [t[0] for t in EDIT_TOOL_TYPES]
        self.assertIn('NONE', tool_ids)
        self.assertIn('CROP', tool_ids)
        self.assertIn('LASSO', tool_ids)

    def test_lasso_constants(self):
        from mixar.modules.moodboard.constants import LASSO_MIN_DISTANCE_THRESHOLD, LASSO_MIN_POINTS
        self.assertGreater(LASSO_MIN_DISTANCE_THRESHOLD, 0)
        self.assertGreaterEqual(LASSO_MIN_POINTS, 3)

    def test_sidebar_dimensions(self):
        from mixar.modules.moodboard.constants import (
            SIDEBAR_WIDTH_DEFAULT, SIDEBAR_MIN_WIDTH, SIDEBAR_MAX_WIDTH,
        )
        self.assertGreaterEqual(SIDEBAR_WIDTH_DEFAULT, SIDEBAR_MIN_WIDTH)
        self.assertLessEqual(SIDEBAR_WIDTH_DEFAULT, SIDEBAR_MAX_WIDTH)


class TestValidateSelectionRegion(unittest.TestCase):
    """Tests for moodboard_utils.validate_selection_region()."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.moodboard.core.moodboard_utils import validate_selection_region
        cls.validate = staticmethod(validate_selection_region)

    def test_valid_region(self):
        state = MagicMock()
        state.box_start_x = 0.1
        state.box_start_y = 0.1
        state.box_end_x = 0.5
        state.box_end_y = 0.5
        is_valid, x1, y1, x2, y2 = self.validate(state)
        self.assertTrue(is_valid)
        self.assertAlmostEqual(x1, 0.1)
        self.assertAlmostEqual(y1, 0.1)
        self.assertAlmostEqual(x2, 0.5)
        self.assertAlmostEqual(y2, 0.5)

    def test_too_small_region(self):
        state = MagicMock()
        state.box_start_x = 0.5
        state.box_start_y = 0.5
        state.box_end_x = 0.5001
        state.box_end_y = 0.5001
        is_valid, x1, y1, x2, y2 = self.validate(state)
        self.assertFalse(is_valid)

    def test_reversed_coordinates_normalized(self):
        state = MagicMock()
        state.box_start_x = 0.8
        state.box_start_y = 0.9
        state.box_end_x = 0.2
        state.box_end_y = 0.1
        is_valid, x1, y1, x2, y2 = self.validate(state)
        self.assertTrue(is_valid)
        self.assertLess(x1, x2)
        self.assertLess(y1, y2)

    def test_custom_min_size(self):
        state = MagicMock()
        state.box_start_x = 0.0
        state.box_start_y = 0.0
        state.box_end_x = 0.005
        state.box_end_y = 0.005
        # Default min_size=0.01, should fail
        is_valid, *_ = self.validate(state)
        self.assertFalse(is_valid)
        # With smaller min_size, should pass
        is_valid, *_ = self.validate(state, min_size=0.001)
        self.assertTrue(is_valid)

    def test_zero_width_invalid(self):
        state = MagicMock()
        state.box_start_x = 0.5
        state.box_start_y = 0.0
        state.box_end_x = 0.5
        state.box_end_y = 1.0
        is_valid, *_ = self.validate(state)
        self.assertFalse(is_valid)

    def test_zero_height_invalid(self):
        state = MagicMock()
        state.box_start_x = 0.0
        state.box_start_y = 0.5
        state.box_end_x = 1.0
        state.box_end_y = 0.5
        is_valid, *_ = self.validate(state)
        self.assertFalse(is_valid)


class TestCalculateOptimalDepthResolution(unittest.TestCase):
    """Tests for lookdev_utils.calculate_optimal_depth_resolution()."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.moodboard.core.lookdev_utils import calculate_optimal_depth_resolution
        cls.calc = staticmethod(calculate_optimal_depth_resolution)

    def test_returns_integer(self):
        result = self.calc(50000, 1920, 1080, 100)
        self.assertIsInstance(result, int)

    def test_result_within_bounds(self):
        for vertices in [10000, 50000, 100000, 200000]:
            for percentage in [50, 100, 150]:
                result = self.calc(vertices, 1920, 1080, percentage)
                self.assertGreaterEqual(result, 25)
                self.assertLessEqual(result, 200)

    def test_high_vertex_count_modest_scaling(self):
        # With >100k vertices and low percentage, should scale up modestly
        result = self.calc(150000, 1920, 1080, 100)
        self.assertGreaterEqual(result, 100)

    def test_low_vertex_count_returns_lower(self):
        result = self.calc(1000, 1920, 1080, 100)
        # Low vertex count yields a smaller optimal resolution
        self.assertLessEqual(result, 100)
        self.assertGreaterEqual(result, 25)

    def test_very_high_percentage_capped(self):
        # When current resolution is already very high, should cap
        result = self.calc(50000, 4096, 4096, 200)
        self.assertLessEqual(result, 200)

    def test_custom_target_file_size(self):
        result_small = self.calc(50000, 1920, 1080, 100, target_file_size_mb=1.0)
        result_large = self.calc(50000, 1920, 1080, 100, target_file_size_mb=10.0)
        # Larger target should allow same or higher resolution
        self.assertLessEqual(result_small, result_large)

    def test_square_resolution(self):
        result = self.calc(50000, 1024, 1024, 100)
        self.assertIsInstance(result, int)

    def test_portrait_resolution(self):
        result = self.calc(50000, 1080, 1920, 100)
        self.assertIsInstance(result, int)


if __name__ == "__main__":
    unittest.main()
