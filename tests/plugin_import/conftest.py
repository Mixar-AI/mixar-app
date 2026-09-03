# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""GPU-module stubs for the onboarding import-step tests.

The root conftest stubs ``bpy`` only. Importing
``mixar.modules.onboarding.core`` pulls in the overlay renderer, which
imports Blender's ``gpu`` / ``blf`` drawing modules — unavailable
outside Blender. Stubbed here rather than in the root conftest so the
rest of the suite keeps running against exactly what it does today.
"""

import sys
from unittest.mock import MagicMock

_GPU_STUB_NAMES = (
    "gpu",
    "gpu.state",
    "gpu.shader",
    "gpu.matrix",
    "gpu.types",
    "gpu_extras",
    "gpu_extras.batch",
    "blf",
    "bgl",
    "mathutils",
    "addon_utils",
)

for _name in _GPU_STUB_NAMES:
    if _name not in sys.modules:
        sys.modules[_name] = MagicMock(name=_name)
