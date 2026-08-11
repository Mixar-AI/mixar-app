# SPDX-FileCopyrightText: 2024 Mixar Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Root-level pytest conftest: pre-stub bpy and related Blender modules so
that tests can be run outside of Blender without import errors."""
import sys
from unittest.mock import MagicMock


def _install_bpy_stubs():
    """Install minimal bpy stub hierarchy into sys.modules."""
    bpy_mock = MagicMock(name='bpy')
    # Register top-level and all known sub-modules that Mixar code imports.
    stub_names = [
        'bpy', 'bpy.types', 'bpy.props', 'bpy.utils', 'bpy.app',
        'bpy.app.handlers', 'bpy.app.timers', 'bpy.context', 'bpy.data',
        'bpy.ops', 'bpy.ops.mixar',
    ]
    for name in stub_names:
        if name not in sys.modules:
            sys.modules[name] = MagicMock(name=name)
    # @persistent must stay a transparent decorator, or every decorated
    # handler imports as a MagicMock and can never be exercised in tests.
    sys.modules['bpy.app.handlers'].persistent = lambda func: func
    # Ensure top-level 'bpy' is the same mock (not two separate ones)
    if 'bpy' not in sys.modules:
        sys.modules['bpy'] = bpy_mock


_install_bpy_stubs()
