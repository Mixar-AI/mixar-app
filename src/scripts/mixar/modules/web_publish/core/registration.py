# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Make the publish properties available without UI auto-discovery.

``--background`` workers run the bootstrap but never the time-budgeted
``modules/**/ui/`` batches, so ``Scene.mixar_web_publish`` would be missing
when the agent's ``publish_scene`` tool runs there. ``ensure_properties``
imports the properties module under the SAME name discovery uses and calls
its idempotent ``register()``; discovery later finds the module in
``sys.modules`` with its classes registered and skips it.
"""

from __future__ import annotations

import importlib

PROPERTIES_MODULE = "mixar.modules.web_publish.ui.properties.web_publish_props"


def ensure_properties() -> bool:
    """Register the publish properties if needed; True when available."""
    import bpy

    if hasattr(bpy.types.Scene, "mixar_web_publish"):
        return True
    importlib.import_module(PROPERTIES_MODULE).register()
    return hasattr(bpy.types.Scene, "mixar_web_publish")
