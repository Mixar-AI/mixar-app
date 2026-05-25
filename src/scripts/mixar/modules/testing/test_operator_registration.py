#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Test script to check operator registration status.

This script verifies that all Mixar operators are properly registered
with Blender. It checks both legacy (wm.m_*) and modern (layers.*)
operator namespaces.

Usage:
    Run inside Blender with:
    blender --background --python src/scripts/mixar/modules/testing/test_operator_registration.py
"""

import bpy
import sys

def check_operator_registration():
    """Check which operators are registered."""

    print("\n" + "="*80)
    print("OPERATOR REGISTRATION STATUS")
    print("="*80)

    # Legacy operators from ui/layer/layer_operators.py
    legacy_operators = [
        'wm.m_refresh_neighbor_uv',
        'wm.m_use_linear_color_space',
        'wm.m_new_layer',
        'wm.m_new_vdm_layer',
        'wm.m_move_layer',
        'wm.m_duplicate_layer',
        'wm.m_delete_layer',
        'wm.m_remove_mp_node',
        'wm.m_toggle_preview_mode',
        'wm.m_layer_viewer',
    ]

    # Modern operators from ui/operators/layer_operators.py
    modern_operators = [
        'layers.add_paint_layer',
        'layers.add_fill_layer',
        'layers.add_layer_group',
        'layers.add_procedural_layer',
        'layers.create_material',
        'layers.select_layer',
        'layers.rename_layer_popup',
        'layers.remove_active_layer',
        'layers.move_layer',
    ]

    print("\nLEGACY OPERATORS (wm.m_*):")
    print("-" * 80)
    legacy_registered = []
    legacy_missing = []

    for op_id in legacy_operators:
        try:
            # Check if operator exists
            op_module, op_name = op_id.split('.')
            op = getattr(getattr(bpy.ops, op_module), op_name, None)

            if op is not None:
                # Try to check if it's valid
                poll_result = "Unknown"
                try:
                    poll_result = "Available" if op.poll() else "Disabled"
                except:
                    poll_result = "Exists"

                print(f"OK: {op_id:40} - {poll_result}")
                legacy_registered.append(op_id)
            else:
                print(f"MISSING: {op_id:40} - NOT REGISTERED")
                legacy_missing.append(op_id)
        except Exception as e:
            print(f"ERROR: {op_id:40} - {e}")
            legacy_missing.append(op_id)

    print("\nMODERN OPERATORS (layers.*):")
    print("-" * 80)
    modern_registered = []
    modern_missing = []

    for op_id in modern_operators:
        try:
            op_module, op_name = op_id.split('.')
            op = getattr(getattr(bpy.ops, op_module), op_name, None)

            if op is not None:
                poll_result = "Unknown"
                try:
                    poll_result = "Available" if op.poll() else "Disabled"
                except:
                    poll_result = "Exists"

                print(f"OK: {op_id:40} - {poll_result}")
                modern_registered.append(op_id)
            else:
                print(f"MISSING: {op_id:40} - NOT REGISTERED")
                modern_missing.append(op_id)
        except Exception as e:
            print(f"ERROR: {op_id:40} - {e}")
            modern_missing.append(op_id)

    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Legacy operators registered: {len(legacy_registered)}/{len(legacy_operators)}")
    print(f"Modern operators registered: {len(modern_registered)}/{len(modern_operators)}")

    if legacy_missing:
        print(f"\nMissing legacy operators ({len(legacy_missing)}):")
        for op in legacy_missing:
            print(f"  - {op}")

    if modern_missing:
        print(f"\nMissing modern operators ({len(modern_missing)}):")
        for op in modern_missing:
            print(f"  - {op}")

    # Check bootstrap loaded modules
    print("\n" + "="*80)
    print("BOOTSTRAP MODULE LOADING")
    print("="*80)

    try:
        from scripts.startup import bootstrap
        if hasattr(bootstrap, '_loaded_modules'):
            print(f"\nBootstrap loaded {len(bootstrap._loaded_modules)} modules")

            # Look for paint-related modules
            paint_modules = [m for m in bootstrap._loaded_modules if 'paint' in str(m)]
            if paint_modules:
                print(f"\nPaint-related modules ({len(paint_modules)}):")
                for mod in paint_modules[:20]:  # Limit to first 20
                    print(f"  - {mod}")
                if len(paint_modules) > 20:
                    print(f"  ... and {len(paint_modules) - 20} more")
        else:
            print("Bootstrap._loaded_modules not found")
    except Exception as e:
        print(f"Error checking bootstrap: {e}")

    print("\n" + "="*80)

    return {
        'legacy_registered': legacy_registered,
        'legacy_missing': legacy_missing,
        'modern_registered': modern_registered,
        'modern_missing': modern_missing,
    }

if __name__ == "__main__":
    try:
        result = check_operator_registration()

        # Exit code: 0 if all registered, 1 if any missing
        if result['legacy_missing'] or result['modern_missing']:
            sys.exit(1)
        else:
            sys.exit(0)
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)
