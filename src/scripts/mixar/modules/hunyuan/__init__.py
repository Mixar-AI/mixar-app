# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Hunyuan 3D Module

Provides AI-powered 3D generation via the Hunyuan API:
- Pro: high-quality 3D from text/image/multi-view
- Rapid: fast 3D from text/image
- Part: mesh decomposition
- Topology: AI retopology
- UV: AI UV unwrapping

Structure:
    core/           -- helpers, callbacks, timer management
    ui/             -- panels, properties, operators
    constants.py    -- module-wide constants
"""

from .ui import hunyuan_properties

# Property modules that need explicit registration (attaches Scene.hunyuan)
property_modules = [hunyuan_properties]


def register():
    """Register Hunyuan property groups and attach Scene.hunyuan."""
    for module in property_modules:
        if hasattr(module, 'register'):
            module.register()


def unregister():
    """Unregister Hunyuan property groups and remove Scene.hunyuan."""
    for module in reversed(property_modules):
        if hasattr(module, 'unregister'):
            module.unregister()
