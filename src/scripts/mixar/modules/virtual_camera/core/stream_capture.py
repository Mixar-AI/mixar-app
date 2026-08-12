# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Camera-POV viewport capture via GPUOffScreen.

Runs on the main thread from the runtime timer (NOT from a draw callback, so
the DRW framebuffer viewport/scissor gotcha does not apply — no region
framebuffer is bound when a timer fires). Raw RGBA bytes are handed to the
encoder worker thread; nothing heavy happens here beyond the GPU readback.
"""

from __future__ import annotations

import bpy
import gpu


class ViewportCapture:
    def __init__(self) -> None:
        self._offscreen = None
        self._size: tuple[int, int] = (0, 0)

    def free(self) -> None:
        if self._offscreen is not None:
            self._offscreen.free()
            self._offscreen = None
        self._size = (0, 0)

    def _ensure_offscreen(self, width: int, height: int):
        if self._offscreen is None or self._size != (width, height):
            self.free()
            self._offscreen = gpu.types.GPUOffScreen(width, height)
            self._size = (width, height)
        return self._offscreen

    @staticmethod
    def _find_view3d():
        wm = bpy.context.window_manager
        if wm is None:
            return None
        for window in wm.windows:
            screen = window.screen
            if screen is None:
                continue
            for area in screen.areas:
                if area.type != 'VIEW_3D':
                    continue
                region = next(
                    (r for r in area.regions if r.type == 'WINDOW'), None
                )
                if region is not None:
                    return area.spaces.active, region
        return None

    @staticmethod
    def frame_size(camera, short_edge: int) -> tuple[int, int]:
        scene = bpy.context.scene
        rd = scene.render if scene else None
        if rd and rd.resolution_x > 0 and rd.resolution_y > 0:
            aspect = rd.resolution_x / rd.resolution_y
        else:
            aspect = 16 / 9
        if aspect >= 1.0:
            width, height = round(short_edge * aspect), short_edge
        else:
            width, height = short_edge, round(short_edge / aspect)
        # GPU-friendly even dimensions
        return max(2, width // 2 * 2), max(2, height // 2 * 2)

    def capture(self, camera, short_edge: int) -> tuple[bytes, int, int] | None:
        """Render *camera*'s POV and read back RGBA8 bytes (bottom-up rows)."""
        view3d = self._find_view3d()
        if view3d is None or camera is None:
            return None
        space, region = view3d
        width, height = self.frame_size(camera, short_edge)

        depsgraph = bpy.context.evaluated_depsgraph_get()
        view_matrix = camera.matrix_world.inverted()
        projection_matrix = camera.calc_matrix_camera(
            depsgraph, x=width, y=height
        )

        # GPU work below may raise when no GPU context is current in the
        # timer tick — the caller counts failures and disables streaming
        # rather than letting one dead subsystem kill camera control.
        offscreen = self._ensure_offscreen(width, height)
        offscreen.draw_view3d(
            bpy.context.scene,
            bpy.context.view_layer,
            space,
            region,
            view_matrix,
            projection_matrix,
            do_color_management=True,
        )

        with offscreen.bind():
            fb = gpu.state.active_framebuffer_get()
            buffer = fb.read_color(0, 0, width, height, 4, 0, 'UBYTE')
        try:
            import numpy as np

            raw = np.frombuffer(buffer, dtype=np.uint8).tobytes()
        except (TypeError, ValueError, ImportError):
            flat = []
            for row in buffer.to_list():
                for px in row:
                    flat.extend(px)
            raw = bytes(flat)
        return raw, width, height
