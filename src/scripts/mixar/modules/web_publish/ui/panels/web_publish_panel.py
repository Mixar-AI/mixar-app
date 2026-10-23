# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export menu › Publish to Web popup.

Draw only: reads the scene's publish properties and a ``PublishState``
snapshot (a lock-guarded copy, no RNA writes). Runtime text arrives as
untranslated templates and is translated here (``iface_``).
"""

import bpy

from mixar.modules.common.i18n import iface_, n_
from mixar.modules.web_publish.core.publish_state import (
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_ERROR,
    format_message,
    get_publish_state,
)

_STATUS_LABELS = {
    "EXPORTING": n_("Exporting scene…"),
    "UPLOADING": n_("Uploading…"),
    "FINALIZING": n_("Finalizing…"),
}
_WRAP = 36


def _wrap(text: str, width: int = _WRAP, limit: int = 6):
    lines, current = [], ""
    for word in (text or "").split():
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines[:limit]


class MIXAR_PT_web_publish(bpy.types.Panel):
    bl_label = "Publish to Web"
    bl_idname = "MIXAR_PT_web_publish"
    bl_space_type = "TOPBAR"
    bl_region_type = "HEADER"
    bl_ui_units_x = 20

    def draw(self, context):
        layout = self.layout
        props = getattr(context.scene, "mixar_web_publish", None)
        if props is None:
            layout.label(text="Publish unavailable", icon="ERROR")
            return
        state = get_publish_state()
        progress, _ = state.snapshot()
        mine = state.scene_name == context.scene.name

        if state.busy:
            if mine:
                self._draw_progress(layout, progress)
            else:
                layout.label(text="Publishing another scene…", icon="SORTTIME")
            return
        if mine and progress.status in (STATUS_ERROR, STATUS_CANCELLED):
            self._draw_error(layout, props, progress)
            return
        if props.is_published:
            self._draw_published(layout, props, progress if mine else None)
            return
        self._draw_form(layout, context, props)

    def _draw_form(self, layout, context, props):
        layout.prop(props, "title", text="", placeholder="Scene title")
        if not props.title.strip():
            from mixar.modules.web_publish.core.publish_state import derive_title

            layout.label(text=iface_("Will publish as “{title}”").format(
                title=derive_title(context.scene.name)), icon="INFO", translate=False)
        layout.prop(props, "description", text="", placeholder="Description")
        layout.prop(props, "visibility", text="Access")
        layout.prop(props, "include_animation")
        col = layout.column(align=True)
        col.scale_y = 1.4
        col.operator("mixar.web_publish", icon="WORLD", text="Publish to Web")
        box = layout.box()
        box.scale_y = 0.85
        box.label(text="Creates a shareable link to an", icon="URL")
        box.label(text="explorable 3D website of this scene.")

    def _draw_progress(self, layout, progress):
        col = layout.column(align=True)
        label = iface_(_STATUS_LABELS.get(progress.status, progress.status))
        col.label(text=label, icon="SORTTIME", translate=False)
        col.progress(factor=progress.progress, type="BAR", text="")
        if progress.detail:
            col.label(text=format_message(iface_(progress.detail), progress.detail_args),
                      translate=False)
        col.operator("mixar.web_publish_cancel", icon="X", text="Cancel")

    def _draw_error(self, layout, props, progress):
        box = layout.box()
        cancelled = progress.status == STATUS_CANCELLED
        box.label(text="Publish cancelled" if cancelled else "Publish failed",
                  icon="CANCEL" if cancelled else "ERROR")
        if not cancelled:
            for chunk in _wrap(format_message(iface_(progress.error), progress.error_args)):
                box.label(text=chunk, translate=False)
        row = box.row(align=True)
        # A failed new version retries as a new version (same link).
        row.operator("mixar.web_publish", text="Retry",
                     icon="FILE_REFRESH").update_existing = props.is_published
        row.operator("mixar.web_publish_dismiss", text="Dismiss")

    def _draw_published(self, layout, props, progress):
        box = layout.box()
        row = box.row(align=True)
        row.label(text=iface_("Live · v{revision}").format(revision=props.revision),
                  icon="WORLD", translate=False)
        if props.last_published:
            right = row.row()
            right.alignment = "RIGHT"
            right.label(text=props.last_published, translate=False)
        url = props.link
        if url:
            box.label(text=url if len(url) <= 44 else url[:41] + "…", icon="URL",
                      translate=False)
        if progress is not None and progress.status == STATUS_DONE and progress.warning:
            for chunk in _wrap(progress.warning, limit=4):
                box.label(text=chunk, translate=False)
        col = box.column(align=True)
        col.operator("mixar.web_publish_copy_link", icon="COPYDOWN", text="Copy Link")
        col.operator("mixar.web_publish_open", icon="WINDOW", text="Open in Browser")

        layout.separator(factor=0.4)
        col = layout.column(align=True)
        col.label(text="Update")
        col.prop(props, "title", text="", placeholder="Scene title")
        col.operator("mixar.web_publish", text="Publish New Version",
                     icon="FILE_REFRESH").update_existing = True
        layout.separator(factor=0.4)
        layout.operator("mixar.web_publish_unpublish", icon="TRASH", text="Unpublish")


classes = (MIXAR_PT_web_publish,)
