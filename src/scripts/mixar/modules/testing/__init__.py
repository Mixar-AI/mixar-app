# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar Testing Module

This module contains all testing utilities and test files for the Mixar
texture painting addon. Tests are organized by functionality:

- test_imports: Tests module import functionality
- test_operator_registration: Tests Blender operator registration
- test_reconnection_performance: Performance benchmarks for node reconnection
- test_baking_operators: Tests for baking operators (BAKING_OT_*)
- test_security_fixes: Tests for security fixes in pixel operations

Usage:
    Run tests inside Blender with:
    blender --background --python src/scripts/mixar/modules/testing/test_imports.py

    Or import individual test modules when needed:
    from mixar.modules.testing import test_imports
    from mixar.modules.testing import test_operator_registration

Note:
    Test modules are NOT imported at addon startup to avoid import errors.
    Import them explicitly when running tests.
"""

# Test modules are not imported at module load time to avoid:
# 1. Import errors breaking addon startup
# 2. Module-level code execution during registration
# 3. Dependencies on modules that may not be available yet
#
# Import test modules explicitly when needed:
#   from mixar.modules.testing import test_imports

__all__ = [
    'test_imports',
    'test_operator_registration',
    'test_baking_operators',
    'test_reconnection_performance',
    'test_security_fixes',
]


def get_test_module(name):
    """Lazily import and return a test module by name.

    Args:
        name: Name of the test module (e.g., 'test_imports')

    Returns:
        The imported test module

    Raises:
        ImportError: If the module cannot be imported
    """
    import importlib
    return importlib.import_module(f'.{name}', __package__)
