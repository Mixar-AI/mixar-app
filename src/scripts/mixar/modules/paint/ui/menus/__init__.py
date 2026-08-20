# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer menus module"""

from . import layer_menus
from .. import operators

modules = [
    operators,
    layer_menus,
]


def register():
    """Register all menu-related modules and their classes.

    Iterates through the modules list and calls each module's register
    function to register Blender classes and handlers.
    """
    for module in modules:
        module.register()


def unregister():
    """Unregister all menu-related modules and their classes.

    Iterates through the modules list in reverse order and calls each
    module's unregister function to clean up Blender classes and handlers.
    """
    for module in reversed(modules):
        module.unregister()
