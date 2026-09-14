# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The ONE definition of the camera Export to Moodboard controls.

Both entry points — the topbar Render menu and the Timeline / Dope Sheet View
menu — open the same popup panel, which calls `draw_camera_export`. Nothing
here is hidden when the scene is not ready: a blocked state names its reason
and offers the fix, because a surface that disappears is precisely why power
users never found the Director's own export.
"""

from ..constants import CAMERA_EXPORT_LABEL
from ..core.camera_export import current_plan, export_settings
from ..core.render_request import describe_range


def _draw_running(layout, settings) -> None:
    column = layout.column(align=True)
    column.progress(
        factor=float(settings.render_progress),
        type='BAR',
        text=settings.render_status or "Rendering…",
    )
    column.label(text="Press Esc over the viewport to cancel", icon='INFO')


def _draw_blocker(layout, scene, camera, plan) -> None:
    """State the blocker, then offer the one action that clears it."""
    box = layout.box()
    box.alert = True
    box.label(text=plan.reason, icon='ERROR')
    if camera is None:
        box.operator("object.camera_add", text="Add Camera", icon='CAMERA_DATA')
        return
    if plan.key_count < 2 and getattr(scene, "mixar_director", None) is not None:
        box.operator(
            "mixar.director_enter",
            text="Animate in Director",
            icon='CAMERA_DATA',
        )


def draw_camera_export(layout, context) -> None:
    """Render the whole surface into *layout*."""
    scene = context.scene
    settings = export_settings(scene)
    if settings is None:
        layout.label(text="Camera export is unavailable", icon='ERROR')
        return

    camera, plan = current_plan(context, settings=settings)

    row = layout.row(align=True)
    row.label(text="Camera", icon='CAMERA_DATA')
    row.prop(settings, "camera_override", text="")
    if camera is not None and settings.camera_override is None:
        layout.label(text=f"Using {camera.name}")

    if settings.render_is_running:
        _draw_running(layout, settings)
        return

    if not plan.ok and plan.key_count < 2:
        # Range, passes and resolution are meaningless until there is motion
        # to render — show the blocker alone rather than a form that cannot
        # be submitted.
        _draw_blocker(layout, scene, camera, plan)
        return

    layout.separator()
    layout.prop(settings, "range_source", text="Range")
    summary = describe_range(plan, scene.render.fps, scene.render.fps_base)
    if summary:
        layout.label(text=summary, icon='TIME')

    layout.separator()
    layout.label(text="Videos")
    layout.prop(settings, "render_output_types", expand=True)
    layout.prop(settings, "render_resolution_percentage")

    if not plan.ok:
        _draw_blocker(layout, scene, camera, plan)

    layout.separator()
    action = layout.column()
    action.enabled = plan.ok
    action.scale_y = 1.3
    action.operator(
        "mixar.render_camera_to_moodboard",
        text=CAMERA_EXPORT_LABEL,
        icon='RENDER_ANIMATION',
    )
