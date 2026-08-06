# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mock bpy module for running unit tests outside of Blender.

Installs minimal bpy stubs into sys.modules so that modules which
do `import bpy` at the top level don't fail during test import.
Only the attributes actually needed for test-reachable code paths
are stubbed; everything else falls back to MagicMock.

Usage:
    # Must be called BEFORE importing any mixar module
    from testing.mock_bpy import install_bpy_mock
    install_bpy_mock()
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock


def _make_bpy_mock():
    """Create a minimal bpy mock with commonly used attributes."""
    bpy = MagicMock()

    # bpy.types
    bpy.types.Panel = type("Panel", (), {})
    bpy.types.Panel.bl_rna = SimpleNamespace(
        properties={"bl_space_type": SimpleNamespace(enum_items=[])}
    )
    bpy.types.Operator = type("Operator", (), {"bl_options": set()})
    bpy.types.PropertyGroup = type("PropertyGroup", (), {})
    bpy.types.Image = MagicMock()
    bpy.types.Scene = MagicMock()

    # bpy.props - return MagicMock callables
    bpy.props.StringProperty = MagicMock(return_value="")
    bpy.props.IntProperty = MagicMock(return_value=0)
    bpy.props.FloatProperty = MagicMock(return_value=0.0)
    bpy.props.BoolProperty = MagicMock(return_value=False)
    bpy.props.EnumProperty = MagicMock(return_value="")
    bpy.props.CollectionProperty = MagicMock(return_value=None)
    bpy.props.PointerProperty = MagicMock(return_value=None)
    bpy.props.FloatVectorProperty = MagicMock(return_value=(0.0, 0.0, 0.0))
    bpy.props.IntVectorProperty = MagicMock(return_value=(0, 0, 0))

    # bpy.utils
    bpy.utils.register_class = MagicMock()
    bpy.utils.unregister_class = MagicMock()
    bpy.utils.previews = MagicMock()
    bpy.utils.resource_path = MagicMock(return_value="/tmp")

    # bpy.app - needs to be a proper MagicMock to support submodule imports
    bpy.app.version = (5, 0, 0)
    bpy.app.version_string = "5.0.0"
    bpy.app.handlers = MagicMock()
    bpy.app.handlers.persistent = lambda fn: fn
    bpy.app.timers = MagicMock()

    # bpy.context
    bpy.context.scene = MagicMock()
    bpy.context.scene.mixie_session_id = ""
    bpy.context.window_manager = MagicMock()
    bpy.context.window_manager.mixie_instance_id = ""

    # bpy.data
    bpy.data.images = MagicMock()
    bpy.data.materials = MagicMock()
    bpy.data.node_groups = MagicMock()

    # bpy.ops
    bpy.ops.object = MagicMock()
    bpy.ops.mesh = MagicMock()
    bpy.ops.render = MagicMock()

    return bpy


def install_bpy_mock():
    """Install bpy mock into sys.modules if not already present."""
    if "bpy" in sys.modules and not isinstance(sys.modules["bpy"], MagicMock):
        return  # Real bpy is available, don't mock

    bpy_mock = _make_bpy_mock()
    sys.modules["bpy"] = bpy_mock
    sys.modules["bpy.types"] = bpy_mock.types
    sys.modules["bpy.props"] = bpy_mock.props
    sys.modules["bpy.utils"] = bpy_mock.utils
    sys.modules["bpy.utils.previews"] = bpy_mock.utils.previews
    # bpy.app must be a MagicMock with __path__ to act as a package
    bpy_app_mock = bpy_mock.app
    bpy_app_mock.__path__ = []  # Makes it look like a package for submodule imports
    sys.modules["bpy.app"] = bpy_app_mock
    sys.modules["bpy.ops"] = bpy_mock.ops
    sys.modules["bpy.path"] = MagicMock()
    sys.modules["bpy.app.handlers"] = bpy_mock.app.handlers
    sys.modules["bpy.app.timers"] = bpy_mock.app.timers
    sys.modules["bmesh"] = MagicMock()
    sys.modules["mathutils"] = MagicMock()
    gpu_mock = MagicMock()
    gpu_mock.__path__ = []
    sys.modules["gpu"] = gpu_mock
    gpu_extras_mock = MagicMock()
    gpu_extras_mock.__path__ = []
    sys.modules["gpu_extras"] = gpu_extras_mock
    sys.modules["bl_math"] = MagicMock()
    sys.modules["idprop"] = MagicMock()
    bpy_extras_mock = MagicMock()
    bpy_extras_mock.__path__ = []  # Makes it look like a package
    sys.modules["bpy_extras"] = bpy_extras_mock
    sys.modules["bpy_extras.image_utils"] = MagicMock()
    sys.modules["bpy_extras.io_utils"] = MagicMock()
    sys.modules["bpy_extras.mesh_utils"] = MagicMock()
    sys.modules["bl_ui"] = MagicMock()
    sys.modules["addon_utils"] = MagicMock()

    # Third-party and Blender-internal modules that may not be available
    for mod_name in [
        "numpy", "numpy.ctypeslib",
        "PIL", "PIL.Image",
        "blf",
        "gpu_extras.batch", "gpu_extras.presets",
        "keyring",
    ]:
        if mod_name not in sys.modules:
            sys.modules[mod_name] = MagicMock()

    # pytest.approx probes ``numpy.bool_`` with isinstance() whenever numpy is
    # importable. A bare MagicMock attribute is not a type, so every approx
    # comparison in the suite would raise TypeError instead of comparing.
    numpy_mock = sys.modules.get("numpy")
    if isinstance(numpy_mock, MagicMock):
        numpy_mock.bool_ = bool


# Auto-install when imported
install_bpy_mock()
