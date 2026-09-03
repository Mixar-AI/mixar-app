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


def _preload_real_optional_modules():
    """Import the real Pillow/numpy before any test module can stub them.

    ``mixar.modules.testing.mock_bpy`` stubs "third-party modules that may not
    be available" only when they are ABSENT from ``sys.modules``, so whichever
    test imports it first decides whether PIL is real for the whole session.
    Collection order then silently decided whether the image tests ran against
    Pillow or against a MagicMock that hands back empty bytes. Importing the
    real packages here — conftest runs before any test module — makes the mock
    the fallback it was meant to be.
    """
    import importlib

    for name in ("numpy", "PIL", "PIL.Image", "PIL.ImageOps"):
        try:
            importlib.import_module(name)
        except ImportError:
            pass


_preload_real_optional_modules()
