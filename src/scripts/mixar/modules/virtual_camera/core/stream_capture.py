# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Camera-POV viewport capture via GPUOffScreen.

**Every GPU call in this module must run from a VIEW_3D draw callback.**
``bpy.app.timers`` ticks are not a guaranteed-GPU moment: on Windows no GL
context is current on the main thread outside the draw loop, so
``GPUOffScreen`` creation and ``draw_view3d`` dereference a null context and
take the process down with an access violation rather than raising something
catchable (on macOS the window context usually *is* current, which is why a
timer-side capture appears to work there). ``space_mixie_chat``'s
``scene_render_ops`` documents the same split; the runtime therefore only
*requests* a frame from its timer and this code runs from the handler.

Drawing an offscreen from inside a region draw resets the region's
framebuffer viewport/scissor (the gotcha in CLAUDE.md), so both are saved and
restored around the draw — otherwise the viewport that serviced the frame
renders black.

Raw RGBA bytes are handed to the encoder worker thread; nothing heavy happens
here beyond the GPU readback.
"""

from __future__ import annotations

import bpy
import gpu


def find_view3d():
    """First open VIEW_3D space + its WINDOW region, or ``None``."""
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
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region is not None:
                return area.spaces.active, region
    return None


class ViewportCapture:
    def __init__(self) -> None:
        self._offscreen = None
        self._size: tuple[int, int] = (0, 0)

    def free(self) -> None:
        """Release the cached offscreen. Draw-callback only, like capture()."""
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

    def capture(self, camera, short_edge: int, space,
                region) -> tuple[bytes, int, int] | None:
        """Render *camera*'s POV and read back RGBA8 bytes (bottom-up rows).

        *space* / *region* are the live draw context's — donors for the shading
        and overlay settings only; the matrices below are the camera's.
        """
        if camera is None or space is None or region is None:
            return None
        width, height = self.frame_size(camera, short_edge)

        depsgraph = bpy.context.evaluated_depsgraph_get()
        view_matrix = camera.matrix_world.inverted()
        projection_matrix = camera.calc_matrix_camera(
            depsgraph, x=width, y=height
        )

        offscreen = self._ensure_offscreen(width, height)
        viewport = gpu.state.viewport_get()
        scissor = gpu.state.scissor_get()
        try:
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
        finally:
            # The offscreen pass leaves its own viewport/scissor behind; the
            # region is still mid-draw and would render black without these.
            gpu.state.viewport_set(*viewport)
            gpu.state.scissor_set(*scissor)

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
