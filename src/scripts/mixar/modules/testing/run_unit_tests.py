# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Unit test runner for Mixar modules.

Discovers and runs all test_*.py files in this directory using unittest.
Can be run standalone or from within Blender.

Usage:
    # Standalone (with mixar on sys.path):
    python run_unit_tests.py

    # Inside Blender:
    blender --background --python src/scripts/mixar/modules/testing/run_unit_tests.py

    # Run specific test module:
    python -m pytest src/scripts/mixar/modules/testing/test_geometry_utils.py -v
"""

import os
import sys
import unittest


def main():
    # Ensure the scripts directory is on sys.path for imports
    test_dir = os.path.dirname(os.path.abspath(__file__))
    scripts_dir = os.path.abspath(os.path.join(test_dir, "..", "..", ".."))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    # Install bpy mock if not running inside Blender
    try:
        import bpy
    except ImportError:
        import importlib.util
        mock_spec = importlib.util.spec_from_file_location(
            "mock_bpy", os.path.join(test_dir, "mock_bpy.py"))
        mock_mod = importlib.util.module_from_spec(mock_spec)
        mock_spec.loader.exec_module(mock_mod)

    # Discover and run all tests
    loader = unittest.TestLoader()
    suite = loader.discover(test_dir, pattern="test_*.py")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
