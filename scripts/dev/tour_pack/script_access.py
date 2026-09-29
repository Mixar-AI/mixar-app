# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Import the tour's beat table outside Blender (``bpy`` stubbed)."""

import os
import sys
from unittest.mock import MagicMock

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_SCRIPTS = os.path.join(_ROOT, "src", "scripts")


def load_tour():
    if _SCRIPTS not in sys.path:
        sys.path.insert(0, _SCRIPTS)
    for name in ("bpy", "gpu", "blf", "gpu_extras", "gpu_extras.batch", "bpy.app",
                 "bpy.app.handlers", "bpy.types", "bpy.props", "bpy.utils"):
        sys.modules.setdefault(name, MagicMock(name=name))
    from mixar.modules.onboarding.core.tour import beats
    return beats.MIXAR_INTRO
