# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Search-result actions — make results usable, not just readable.

``mixie.locate_search_result`` points the CURRENT asset browser at the hit
(switch to its library + set the name filter), so the user sees the real
thumbnail and can drag it in — the browser itself is the preview surface.
``mixie.clear_search_results`` resets the results block.
"""

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


class MIXIE_OT_locate_search_result(Operator):
    """Show this asset in the asset browser (switch library + filter by name)"""

    bl_idname = "mixie.locate_search_result"
    bl_label = "Locate Asset"
    bl_description = (
        "Point the asset browser at this result: switch to its library and "
        "filter by its name, so you can see it and drag it into the scene"
    )
    bl_options = {"REGISTER"}

    asset_name: bpy.props.StringProperty(default="")
    library: bpy.props.StringProperty(default="")

    def execute(self, context):
        space = context.space_data
        params = getattr(space, "params", None)
        if params is None:
            self.report({"WARNING"}, "Not inside an asset browser")
            return {"CANCELLED"}

        if self.library:
            # Property name differs across Blender versions.
            for attr in ("asset_library_reference", "asset_library_ref"):
                if hasattr(params, attr):
                    try:
                        setattr(params, attr, self.library)
                    except Exception:
                        self.report(
                            {"WARNING"},
                            f"Library '{self.library}' is not available",
                        )
                        return {"CANCELLED"}
                    break

        if hasattr(params, "filter_search"):
            params.filter_search = self.asset_name

        for area in context.screen.areas:
            if area.type == 'FILE_BROWSER':
                area.tag_redraw()
        self.report({"INFO"}, f"Showing '{self.asset_name}' in {self.library}")
        return {"FINISHED"}


class MIXIE_OT_clear_search_results(Operator):
    """Clear the search results"""

    bl_idname = "mixie.clear_search_results"
    bl_label = "Clear Results"
    bl_description = "Clear the asset search results"
    bl_options = {"REGISTER"}

    def execute(self, context):
        state = getattr(context.scene, 'mixie_asset_training', None)
        if state:
            state.search_results.clear()
            state.search_message = ""
        return {"FINISHED"}


classes = (
    MIXIE_OT_locate_search_result,
    MIXIE_OT_clear_search_results,
)
