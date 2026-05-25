# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for texel_density module.

Tests constants and the saturate() pure utility function.
Blender-dependent functions (calculate_geometry_areas, etc.)
require a full bpy context and are tested separately.
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


class TestSaturate(unittest.TestCase):
    """Tests for texel_density.texel.utils.saturate() clamping function."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.texel_density.texel.utils import saturate
        cls.saturate = staticmethod(saturate)

    def test_value_in_range(self):
        self.assertEqual(self.saturate(0.5), 0.5)

    def test_value_at_zero(self):
        self.assertEqual(self.saturate(0.0), 0.0)

    def test_value_at_one(self):
        self.assertEqual(self.saturate(1.0), 1.0)

    def test_value_below_zero(self):
        self.assertEqual(self.saturate(-0.5), 0)

    def test_value_above_one(self):
        self.assertEqual(self.saturate(1.5), 1)

    def test_large_negative(self):
        self.assertEqual(self.saturate(-100), 0)

    def test_large_positive(self):
        self.assertEqual(self.saturate(100), 1)


class TestTexelDensityConstants(unittest.TestCase):
    """Tests for texel_density.texel.constants."""

    def test_preset_values_structure(self):
        from mixar.modules.texel_density.texel.constants import TD_PRESET_VALUES
        # Should have entries for each unit type: 0, 1, 2, 3
        for unit in ['0', '1', '2', '3']:
            self.assertIn(unit, TD_PRESET_VALUES)
            self.assertEqual(len(TD_PRESET_VALUES[unit]), 2)
            for row in TD_PRESET_VALUES[unit]:
                self.assertEqual(len(row), 3)
                for val in row:
                    self.assertIsInstance(val, str)

    def test_texture_size_items(self):
        from mixar.modules.texel_density.texel.constants import TD_TEXTURE_SIZE_ITEMS
        sizes = [item[0] for item in TD_TEXTURE_SIZE_ITEMS]
        self.assertIn('512', sizes)
        self.assertIn('1024', sizes)
        self.assertIn('2048', sizes)
        self.assertIn('4096', sizes)
        self.assertIn('CUSTOM', sizes)

    def test_units_items(self):
        from mixar.modules.texel_density.texel.constants import TD_UNITS_ITEMS
        unit_ids = [item[0] for item in TD_UNITS_ITEMS]
        self.assertEqual(unit_ids, ['0', '1', '2', '3'])
        unit_labels = [item[1] for item in TD_UNITS_ITEMS]
        self.assertIn('px/cm', unit_labels)
        self.assertIn('px/m', unit_labels)
        self.assertIn('px/in', unit_labels)
        self.assertIn('px/ft', unit_labels)

    def test_set_method_items(self):
        from mixar.modules.texel_density.texel.constants import TD_SET_METHOD_ITEMS
        methods = [item[0] for item in TD_SET_METHOD_ITEMS]
        self.assertIn('EACH', methods)
        self.assertIn('AVERAGE', methods)

    def test_bake_vc_mode_items(self):
        from mixar.modules.texel_density.texel.constants import TD_BAKE_VC_MODE_ITEMS
        modes = [item[0] for item in TD_BAKE_VC_MODE_ITEMS]
        self.assertIn('TD_FACES_TO_VC', modes)
        self.assertIn('TD_ISLANDS_TO_VC', modes)
        self.assertIn('UV_ISLANDS_TO_VC', modes)
        self.assertIn('DISTORTION', modes)

    def test_select_type_items(self):
        from mixar.modules.texel_density.texel.constants import TD_SELECT_TYPE_ITEMS
        types = [item[0] for item in TD_SELECT_TYPE_ITEMS]
        self.assertIn('EQUAL', types)
        self.assertIn('LESS', types)
        self.assertIn('GREATER', types)

    def test_backend_items(self):
        from mixar.modules.texel_density.texel.constants import PREFS_BACKEND_ITEMS
        backends = [item[0] for item in PREFS_BACKEND_ITEMS]
        self.assertIn('CPP', backends)
        self.assertIn('PY', backends)

    def test_asset_names(self):
        from mixar.modules.texel_density.texel.constants import TD_VC_NAME, TD_MATERIAL_NAME
        self.assertEqual(TD_VC_NAME, 'td_vis')
        self.assertEqual(TD_MATERIAL_NAME, 'TD_Checker')

    def test_shader_sources_not_empty(self):
        from mixar.modules.texel_density.texel.constants import (
            VERTEX_SHADER_TEXT_3_0, FRAGMENT_SHADER_TEXT_3_0,
            VERTEX_SHADER_TEXT_3_3, FRAGMENT_SHADER_TEXT_3_3,
        )
        self.assertGreater(len(VERTEX_SHADER_TEXT_3_0), 0)
        self.assertGreater(len(FRAGMENT_SHADER_TEXT_3_0), 0)
        self.assertGreater(len(VERTEX_SHADER_TEXT_3_3), 0)
        self.assertGreater(len(FRAGMENT_SHADER_TEXT_3_3), 0)

    def test_anchor_origin_items(self):
        from mixar.modules.texel_density.texel.constants import TD_ANCHOR_ORIGIN_ITEMS
        anchors = [item[0] for item in TD_ANCHOR_ORIGIN_ITEMS]
        self.assertIn('SELECTION', anchors)
        self.assertIn('UV_CENTER', anchors)
        self.assertIn('2D_CURSOR', anchors)


if __name__ == "__main__":
    unittest.main()
