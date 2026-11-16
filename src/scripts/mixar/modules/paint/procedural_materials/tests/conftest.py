# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pytest configuration: pre-stub bpy and related Blender modules before any
package __init__.py is imported, so tests can run outside of Blender."""
import sys
import types
from unittest.mock import MagicMock


def _make_bpy_stub():
    """Return a module-like MagicMock hierarchy for bpy."""
    bpy = MagicMock(name='bpy')
    # Ensure submodules are proper MagicMocks in sys.modules
    for submod in ('bpy.types', 'bpy.props', 'bpy.utils', 'bpy.app',
                   'bpy.app.timers', 'bpy.context', 'bpy.data',
                   'bpy.ops', 'bpy.ops.mixar'):
        sys.modules.setdefault(submod, MagicMock(name=submod))
    return bpy


# Install stubs before any test collection imports the package tree.
if 'bpy' not in sys.modules:
    sys.modules['bpy'] = _make_bpy_stub()
else:
    # Ensure sub-modules are also registered
    _make_bpy_stub()
