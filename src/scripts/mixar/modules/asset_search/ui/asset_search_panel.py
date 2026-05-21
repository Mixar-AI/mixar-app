# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Asset Library Search Panel

Panel in the asset browser's source list (TOOLS region) for training
an asset search model, checking status, and searching indexed assets.
"""

import bpy
from bpy.types import Panel


class MIXIE_PT_asset_library_search(Panel):
    """Asset Library Search panel in the asset browser source list"""

    bl_label = "Asset Library Search"
    bl_idname = "MIXIE_PT_asset_library_search"
    bl_space_type = 'FILE_BROWSER'
    bl_region_type = 'TOOLS'
    bl_order = 100  # Appear after built-in panels

    @classmethod
    def poll(cls, context):
        from bpy_extras.asset_utils import SpaceAssetInfo
        return SpaceAssetInfo.is_asset_browser_poll(context)

    def draw(self, context):
        layout = self.layout
        state = getattr(context.scene, 'mixie_asset_training', None)
        is_training = state.is_training if state else False

        # == Model section ==
        model_box = layout.box()
        col = model_box.column(align=True)

        if is_training:
            col.prop(state, "progress", text="Training...", slider=True)
            col.enabled = False
        else:
            row = col.row(align=True)
            row.scale_y = 1.3
            row.operator(
                "mixie.train_asset_model",
                text="Train Model",
                icon='OUTLINER_OB_LIGHT',
            )
            # Compact refresh — icon-only, doesn't stretch
            refresh_sub = row.row(align=True)
            refresh_sub.scale_x = 0.8
            if state and state.is_refreshing:
                refresh_sub.enabled = False
                refresh_sub.operator(
                    "mixie.refresh_asset_status",
                    text="",
                    icon='SORTTIME',
                )
            else:
                refresh_sub.operator(
                    "mixie.refresh_asset_status",
                    text="",
                    icon='FILE_REFRESH',
                )

            # Stale-embeddings warning
            if state and state.needs_retraining:
                col.separator(factor=0.3)
                alert_row = col.row()
                alert_row.alert = True
                alert_row.label(
                    text=state.retraining_message
                    or "Retrain to update embeddings",
                    icon='ERROR',
                )

        layout.separator(factor=0.5)

        # == Search section ==
        search_col = layout.column()

        if state:
            # Text prompt
            search_col.prop(state, "search_prompt", text="", icon='VIEWZOOM')
            search_col.separator(factor=0.3)

            # Reference image (compact)
            search_col.label(text="Reference Image", icon='IMAGE_DATA')
            search_col.template_ID(
                state, "search_image", open="image.open",
            )
            search_col.separator(factor=0.5)

        # Search button
        btn_row = search_col.row(align=True)
        btn_row.scale_y = 1.5
        if state and state.is_searching:
            btn_row.enabled = False
            btn_row.operator(
                "mixie.search_assets",
                text="Searching...",
                icon='SORTTIME',
            )
        else:
            btn_row.operator(
                "mixie.search_assets",
                text="Search",
                icon='VIEWZOOM',
            )

        # Results
        if state and state.search_message:
            layout.separator(factor=0.5)
            result_box = search_col.box()
            lines = state.search_message.split("\n")
            # Header line (e.g. "Found 3 results:")
            if lines:
                header = result_box.row()
                header.scale_y = 0.9
                header.label(text=lines[0], icon='CHECKMARK')
            # Individual results
            for line in lines[1:]:
                if line.strip():
                    r = result_box.row()
                    r.scale_y = 0.85
                    r.label(text="    " + line)

        # Grey out entire search section during training
        if is_training:
            search_col.enabled = False


classes = (
    MIXIE_PT_asset_library_search,
)
