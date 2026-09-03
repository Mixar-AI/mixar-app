# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""VIEW_3D N-panel: the "Web" tab for publishing the scene as a 3D website."""

import bpy

from mixar.modules.web_publish.core.publish_state import (
    STATUS_ERROR,
)


def _props(context):
    return getattr(context.scene, "mixar_web_publish", None)


class MIXAR_PT_web_publish(bpy.types.Panel):
    bl_label = "Publish to Web"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Mixar"
    bl_order = 55

    def draw(self, context):
        layout = self.layout
        props = _props(context)
        if props is None:
            layout.label(text="Publish unavailable", icon="ERROR")
            return

        if props.is_busy:
            self._draw_progress(layout, props)
            return

        if props.status == STATUS_ERROR and props.error_message:
            self._draw_error(layout, props)
            return

        if props.is_published:
            self._draw_published(layout, context, props)
            return

        self._draw_publish_form(layout, context, props)

    # ------------------------------------------------------------------

    def _draw_publish_form(self, layout, context, props):
        title = props.title or ""
        row = layout.row()
        row.prop(props, "title", text="", placeholder="Scene title", icon="NONE")
        if not title.strip():
            # surface the derived default so an empty field is never a surprise
            from mixar.modules.web_publish.core.publish_state import derive_title

            layout.label(
                text=f"Will publish as “{derive_title(context.scene.name)}”",
                icon="INFO",
            )

        layout.prop(props, "description", text="")
        layout.prop(props, "visibility", text="Access")
        layout.prop(props, "include_animation")

        col = layout.column(align=True)
        col.scale_y = 1.4
        col.operator("mixar.web_publish", icon="WORLD", text="Publish to Web")

        box = layout.box()
        box.scale_y = 0.85
        box.label(text="Creates a shareable link to an", icon="URL")
        box.label(text="explorable 3D website of this scene.")
        box.label(text="Update any time from the same panel.")

    def _draw_progress(self, layout, props):
        col = layout.column(align=True)
        col.label(text=_STATUS_LABELS.get(props.status, props.status), icon="SORTTIME")
        col.progress(factor=props.progress, type="BAR", text="")
        if props.status_detail:
            col.label(text=props.status_detail)
        col.operator("mixar.web_publish_cancel", icon="X", text="Cancel")

    def _draw_error(self, layout, props):
        box = layout.box()
        box.label(text="Publish failed", icon="ERROR")
        message = props.error_message
        for chunk in _wrap(message, 36):
            box.label(text=chunk)
        row = box.row(align=True)
        row.operator("mixar.web_publish", text="Retry", icon="FILE_REFRESH")
        row.operator("mixar.web_publish_clear_error", text="Dismiss")

    def _draw_published(self, layout, context, props):
        box = layout.box()
        row = box.row(align=True)
        row.label(text=f"Live  •  v{props.revision}", icon="WORLD")
        if props.last_published:
            right = row.row()
            right.alignment = "RIGHT"
            right.label(text=props.last_published)

        url = props.viewer_url or props.share_url
        if url:
            display = url if len(url) <= 44 else url[:41] + "…"
            box.label(text=display, icon="URL")

        col = box.column(align=True)
        col.operator("mixar.web_publish_copy_link", icon="COPYDOWN", text="Copy Link")
        col.operator("mixar.web_publish_open", icon="WINDOW", text="Open in Browser")

        layout.separator(factor=0.4)
        col = layout.column(align=True)
        col.label(text="Update:")
        col.prop(props, "title", text="")
        col.operator(
            "mixar.web_publish", text="Publish New Version", icon="FILE_REFRESH"
        ).update_existing = True

        layout.separator(factor=0.4)
        layout.operator("mixar.web_publish_unpublish", icon="TRASH", text="Unpublish")


_STATUS_LABELS = {
    "EXPORTING": "Exporting scene…",
    "UPLOADING": "Uploading…",
    "FINALIZING": "Finalizing…",
}


def _wrap(text: str, width: int):
    text = (text or "").strip()
    if not text:
        return []
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines[:6]


classes = (MIXAR_PT_web_publish,)
