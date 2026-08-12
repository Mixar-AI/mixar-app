# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Virtual Camera N-panel (View3D sidebar).

Read-only view over the server/runtime singletons plus lifecycle buttons —
control settings (lens, smoothing, scale, FPS) belong to the phone app, so
they are shown as status only, never as editable duplicated state.
"""

from __future__ import annotations

from bpy.types import Panel

from mixar.modules.virtual_camera.core import qr_icon
from mixar.modules.virtual_camera.core.runtime import get_runtime


class MIXAR_PT_virtual_camera(Panel):
    bl_label = "Virtual Camera"
    bl_idname = "MIXAR_PT_virtual_camera"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Virtual Camera"

    def draw(self, context):
        layout = self.layout
        runtime = get_runtime()
        state = runtime.server.state

        if not state.running:
            col = layout.column()
            col.label(text="Use your phone as a camera:", icon='CAMERA_DATA')
            col.label(text="motion control + live viewport.")
            col.separator()
            col.operator("mixar.virtual_camera_start", icon='PLAY')
            if state.last_error:
                row = col.row()
                row.alert = True
                row.label(text=state.last_error, icon='ERROR')
            return

        # -- pairing block
        box = layout.box()
        if state.phone_connected:
            box.label(text="Phone connected", icon='CHECKMARK')
            device = runtime.server.session.device_info.get("ua", "")
            if "iPhone" in device or "iPad" in device:
                box.label(text="iOS device", icon='OUTLINER_OB_CAMERA')
        else:
            box.label(text="Scan with the phone camera:", icon='VIEW_CAMERA')
            icon_id = qr_icon.get_qr_icon_id(state.url)
            if icon_id:
                box.template_icon(icon_value=icon_id, scale=8.0)
            box.label(text=state.url)
            if not state.tls:
                warn = box.row()
                warn.alert = True
                warn.label(text="No TLS: joystick control only", icon='ERROR')

        row = layout.row(align=True)
        row.operator("mixar.virtual_camera_copy_url", text="Copy Link", icon='COPYDOWN')
        row.operator("mixar.virtual_camera_new_pairing", text="Re-pair", icon='FILE_REFRESH')

        # -- live status
        cam = runtime.driver.camera()
        col = layout.column(align=True)
        col.label(text=f"Camera: {cam.name if cam else '—'}", icon='CAMERA_DATA')
        if state.phone_connected:
            settings = runtime.server.session.snapshot_settings()
            col.label(text=f"Lens: {settings['lens']:.0f} mm")
            fps = settings["stream_fps"]
            col.label(text=f"Stream: {'off' if not fps else f'{fps:.0f} fps'}")
            if runtime.driver.recording:
                rec = col.row()
                rec.alert = True
                rec.label(text="Recording keyframes", icon='REC')

        if runtime.last_error:
            err = layout.row()
            err.alert = True
            err.label(text=runtime.last_error, icon='ERROR')

        layout.separator()
        layout.operator("mixar.virtual_camera_stop", icon='PAUSE')


classes = (MIXAR_PT_virtual_camera,)
