# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Test script for paint module imports.

This script tests that all Mixar paint module components can be imported
successfully and that required functions are available.

Usage:
    Run inside Blender:
    blender --background --python src/scripts/mixar/modules/testing/test_imports.py
"""

import bpy

try:
    print("Testing paint module registration...")
    from mixar.modules import paint
    print("OK: Paint module imported successfully")

    # Test layer helper modules exist
    from mixar.modules.paint.ui.layer.helpers import layer_create_helpers
    print("OK: layer_create_helpers module exists")

    from mixar.modules.paint.ui.layer.helpers import layer_operation_helpers
    print("OK: layer_operation_helpers module exists")

    from mixar.modules.paint.ui.layer.helpers import layer_enum_helpers
    print("OK: layer_enum_helpers module exists")

    from mixar.modules.paint.ui.layer.helpers import layer_removal_helpers
    print("OK: layer_removal_helpers module exists")

    # Test core connection modules
    from mixar.modules.paint.core.io.connections import layer_connections
    print("OK: layer_connections module exists")

    # Test specific functions
    assert hasattr(layer_create_helpers, 'add_new_layer'), "add_new_layer not found"
    print("OK: add_new_layer function found")

    assert hasattr(layer_enum_helpers, 'get_normal_map_type_items'), "get_normal_map_type_items not found"
    print("OK: get_normal_map_type_items function found")

    assert hasattr(layer_connections, 'reconnect_layer_nodes'), "reconnect_layer_nodes not found"
    print("OK: reconnect_layer_nodes function found")

    print("\n=== ALL TESTS PASSED ===")

except Exception as e:
    print(f"\n=== TEST FAILED ===")
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
