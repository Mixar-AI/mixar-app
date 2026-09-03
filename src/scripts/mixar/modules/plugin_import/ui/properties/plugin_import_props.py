# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""WindowManager-attached state for the plugin-import checklist.

Transient session state (a scan result + the user's enable checkboxes),
so it lives on WindowManager — it must not persist in the .blend or take
part in undo.
"""

from __future__ import annotations

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


class MixiePluginItem(PropertyGroup):
    """One discovered plugin row in the import checklist."""

    name: StringProperty(name="Name", default="")
    label: StringProperty(name="Label", default="")
    kind: StringProperty(name="Kind", default="")  # 'addon' | 'extension'
    enable: BoolProperty(
        name="Enable",
        description="Enable this plugin in Mixar after importing it",
        default=True,
    )
    status: StringProperty(name="Status", default="")


class MixiePluginImportState(PropertyGroup):
    """Scan results + summary for the plugin-import panel."""

    source_version: StringProperty(name="Blender Version", default="")
    source_path: StringProperty(name="Source Path", default="")
    scanned: BoolProperty(default=False)
    plugins: CollectionProperty(type=MixiePluginItem)
    active_index: IntProperty(default=0)
    last_summary: StringProperty(default="")

    # Collapse state for the Preferences > Add-ons section. That host has
    # HIDE_HEADER, so the section draws its own disclosure triangle off
    # this flag instead of getting a real panel header.
    show_panel: BoolProperty(
        name="Show Blender Plugin Import",
        description="Expand the Blender plugin import section",
        default=True,
    )


classes = (
    MixiePluginItem,
    MixiePluginImportState,
)


def register():
    from bpy.utils import register_class

    for cls in classes:
        register_class(cls)
    bpy.types.WindowManager.mixie_plugin_import = bpy.props.PointerProperty(
        type=MixiePluginImportState
    )


def unregister():
    from bpy.utils import unregister_class

    if hasattr(bpy.types.WindowManager, "mixie_plugin_import"):
        del bpy.types.WindowManager.mixie_plugin_import
    for cls in reversed(classes):
        unregister_class(cls)
