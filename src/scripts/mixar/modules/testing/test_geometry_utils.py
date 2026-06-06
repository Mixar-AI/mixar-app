# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for common.geometry_utils module.

Tests the ray-casting point-in-polygon algorithm used across
moodboard, paint, and selection modules.
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


class TestPointInPolygon(unittest.TestCase):
    """Tests for point_in_polygon() ray-casting algorithm."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.common.geometry_utils import point_in_polygon as _pip
        cls.pip = lambda self, *a, **kw: _pip(*a, **kw)

    # ------------------------------------------------------------------
    # Basic containment
    # ------------------------------------------------------------------

    def test_point_inside_square(self):
        square = [(0, 0), (10, 0), (10, 10), (0, 10)]
        self.assertTrue(self.pip(5, 5, square))

    def test_point_outside_square(self):
        square = [(0, 0), (10, 0), (10, 10), (0, 10)]
        self.assertFalse(self.pip(15, 5, square))

    def test_point_above_square(self):
        square = [(0, 0), (10, 0), (10, 10), (0, 10)]
        self.assertFalse(self.pip(5, 15, square))

    def test_point_below_square(self):
        square = [(0, 0), (10, 0), (10, 10), (0, 10)]
        self.assertFalse(self.pip(5, -5, square))

    # ------------------------------------------------------------------
    # Triangle
    # ------------------------------------------------------------------

    def test_point_inside_triangle(self):
        triangle = [(0, 0), (10, 0), (5, 10)]
        self.assertTrue(self.pip(5, 3, triangle))

    def test_point_outside_triangle(self):
        triangle = [(0, 0), (10, 0), (5, 10)]
        self.assertFalse(self.pip(0, 10, triangle))

    # ------------------------------------------------------------------
    # Concave polygon (L-shape)
    # ------------------------------------------------------------------

    def test_point_inside_concave_polygon(self):
        # L-shaped polygon
        L = [(0, 0), (5, 0), (5, 5), (10, 5), (10, 10), (0, 10)]
        self.assertTrue(self.pip(2, 2, L))  # bottom-left area
        self.assertTrue(self.pip(7, 7, L))  # top-right area

    def test_point_in_concavity(self):
        L = [(0, 0), (5, 0), (5, 5), (10, 5), (10, 10), (0, 10)]
        self.assertFalse(self.pip(7, 2, L))  # inside the notch

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_degenerate_polygon_less_than_3_vertices(self):
        self.assertFalse(self.pip(0, 0, []))
        self.assertFalse(self.pip(0, 0, [(0, 0)]))
        self.assertFalse(self.pip(0, 0, [(0, 0), (1, 1)]))

    def test_negative_coordinates(self):
        square = [(-10, -10), (10, -10), (10, 10), (-10, 10)]
        self.assertTrue(self.pip(0, 0, square))
        self.assertTrue(self.pip(-5, -5, square))
        self.assertFalse(self.pip(-15, 0, square))

    def test_large_polygon(self):
        import math
        # Circle approximation with 100 vertices
        n = 100
        radius = 50
        circle = [
            (radius * math.cos(2 * math.pi * i / n),
             radius * math.sin(2 * math.pi * i / n))
            for i in range(n)
        ]
        self.assertTrue(self.pip(0, 0, circle))
        self.assertTrue(self.pip(25, 0, circle))
        self.assertFalse(self.pip(55, 0, circle))

    def test_point_at_origin_in_centered_polygon(self):
        diamond = [(0, 5), (5, 0), (0, -5), (-5, 0)]
        self.assertTrue(self.pip(0, 0, diamond))

    def test_float_coordinates(self):
        square = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        self.assertTrue(self.pip(0.5, 0.5, square))
        self.assertFalse(self.pip(1.5, 0.5, square))


class TestPointInPolygonPerformance(unittest.TestCase):
    """Performance sanity checks for point_in_polygon."""

    @classmethod
    def setUpClass(cls):
        from mixar.modules.common.geometry_utils import point_in_polygon as _pip
        cls.pip = lambda self, *a, **kw: _pip(*a, **kw)

    def test_many_calls_complete_quickly(self):
        import time
        square = [(0, 0), (100, 0), (100, 100), (0, 100)]
        start = time.perf_counter()
        for _ in range(10000):
            self.pip(50, 50, square)
        elapsed = time.perf_counter() - start
        # Should complete well under 1 second
        self.assertLess(elapsed, 1.0, "10,000 point-in-polygon calls took too long")


if __name__ == "__main__":
    unittest.main()
