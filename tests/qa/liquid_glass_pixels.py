# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""GPU checks run INSIDE the real app by liquid_glass_e2e.py.

Compile the product's exact shader sources. Exercise rounded clipping, whole
material fades, translated coordinates and optional backdrop on the active GPU.
The scenario also captures production surfaces; these swatches isolate the
material from window-manager effects and do not validate native OS frost.
"""

from pathlib import Path
import re

import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix


def _shader(root, backdrop):
    src = (root / "src/source/blender/editors/interface/interface_mixar_glass_shader.hh").read_text()
    vertex, fragment = re.findall(r'R"GLSL\((.*?)\)GLSL"', src, re.S)
    info = gpu.types.GPUShaderCreateInfo()
    iface = gpu.types.GPUStageInterfaceInfo("mixar_glass_iface_qa")
    iface.no_perspective('VEC2', "localPos")
    info.vertex_in(0, 'VEC2', "pos")
    info.vertex_out(iface)
    info.fragment_out(0, 'VEC4', "fragColor")
    info.push_constant('MAT4', "ModelViewProjectionMatrix")
    info.push_constant('BOOL', "srgbTarget")
    for name in ("pane", "metrics", "tintTop", "tintBottom", "sheen", "rim"):
        info.push_constant('VEC4', name)
    if backdrop:
        info.define("GLASS_BACKDROP")
        info.sampler(0, 'FLOAT_2D', "image")
        for name in ("sourceRect", "glaze", "lighting"):
            info.push_constant('VEC4', name)
    info.vertex_source(vertex)
    info.fragment_source(fragment)
    return gpu.shader.create_from_info(info)


def _render(shader, scale, alpha, backdrop=None, translate=0, linear=False):
    width, height = 320 * scale, 100 * scale
    off = gpu.types.GPUOffScreen(width, height, format='RGBA32F')
    try:
        with off.bind(), gpu.matrix.push_pop():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0, 0, 0, 0))
            gpu.state.viewport_set(0, 0, width, height)
            gpu.state.blend_set('ALPHA_PREMULT')
            gpu.state.depth_test_set('NONE')
            gpu.matrix.load_matrix(Matrix.Identity(4))
            projection = Matrix(((2 / width, 0, 0, -1), (0, 2 / height, 0, -1),
                                 (0, 0, 1, 0), (0, 0, 0, 1)))
            # Translate the entire coordinate system, like the island region.
            projection @= Matrix.Translation((-translate, 0, 0))
            gpu.matrix.load_projection_matrix(projection)
            x0, x1 = 20 * scale + translate, 300 * scale + translate
            y0, y1 = 20 * scale, 80 * scale
            batch = batch_for_shader(shader, 'TRI_FAN', {'pos': (
                (x0 - scale, y0 - scale), (x1 + scale, y0 - scale),
                (x1 + scale, y1 + scale), (x0 - scale, y1 + scale))})
            shader.bind()
            shader.uniform_float("ModelViewProjectionMatrix", projection)
            shader.uniform_int("srgbTarget", int(linear))
            shader.uniform_float("pane", (x0, y0, x1, y1))
            shader.uniform_float("metrics", (30 * scale, scale, 10 * scale, alpha))
            shader.uniform_float("tintTop", (0.09, 0.12, 0.10, 0.16))
            shader.uniform_float("tintBottom", (0.04, 0.055, 0.048, 0.24))
            shader.uniform_float("sheen", (1, 1, 1, 0.14))
            shader.uniform_float("rim", (1, 1, 1, 0.14))
            if backdrop:
                shader.uniform_float("sourceRect", (translate, 0, width + translate, height))
                shader.uniform_float("glaze", (0.071, 0.071, 0.071, 0.22))
                shader.uniform_float("lighting", (0.6 * scale, 0.1, 26 * scale, 160 * scale))
                shader.uniform_sampler("image", backdrop)
            batch.draw(shader)
            pixels = np.array(fb.read_color(0, 0, width, height, 4, 0, 'FLOAT'))
            return pixels.reshape(height, width, 4).copy()
    finally:
        off.free()


def _save(pixels, path):
    height, width = pixels.shape[:2]
    # Show the premultiplied material over middle grey for visual inspection.
    rgba = pixels.copy()
    rgba[:, :, :3] += 0.30 * (1 - rgba[:, :, 3:4])
    rgba[:, :, 3] = 1
    img = bpy.data.images.new("QA glass swatch", width=width, height=height, alpha=True)
    try:
        img.colorspace_settings.name = 'Non-Color'
        img.pixels.foreach_set(rgba.ravel())
        img.filepath_raw = str(path)
        img.file_format = 'PNG'
        img.save()
    finally:
        bpy.data.images.remove(img)


def run(root, out):
    root, out = Path(root), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    old_blend = gpu.state.blend_get()
    old_depth = gpu.state.depth_test_get()
    old_viewport = gpu.state.viewport_get()
    old_projection = gpu.matrix.get_projection_matrix().copy()
    verdict = []
    try:
        for has_backdrop in (False, True):
            shader = _shader(root, has_backdrop)
            # High-frequency source deliberately exposes a rectangular bed leak.
            data = np.ones((64, 64, 4), dtype=np.float32)
            data[:, :, :3] = (np.indices((64, 64)).sum(axis=0) % 2)[:, :, None] * 0.7
            tex = gpu.types.GPUTexture((64, 64), format='RGBA32F',
                                      data=gpu.types.Buffer('FLOAT', data.shape, data)) if has_backdrop else None
            for scale in (1, 2):
                full = _render(shader, scale, 1, tex)
                half = _render(shader, scale, 0.5, tex)
                moved = _render(shader, scale, 1, tex, translate=137 * scale)
                linear = _render(shader, scale, 1, tex, linear=True)
                assert np.allclose(linear[:, :, 3], full[:, :, 3], atol=0.002), "colour conversion changes coverage"
                assert np.all(linear[:, :, :3] <= full[:, :, :3] + 0.002), "sRGB target misses colour conversion"
                assert np.max(full[:, :, :3] - linear[:, :, :3]) > 0.005, "sRGB conversion has no effect"
                assert np.isfinite(full).all(), "shader produced invalid pixels"
                assert np.allclose(half, full * 0.5, atol=0.002), "pane layers fade separately"
                assert np.allclose(moved, full, atol=0.003), "translated pane changes its material"
                assert np.max(full[20 * scale:24 * scale, 20 * scale:24 * scale]) < 0.001, "corner leaks"
                assert full[50 * scale, 160 * scale, 3] > 0.15, "body is invisible"
                assert np.all(full[:, :, :3] <= full[:, :, 3:4] + 0.001), "RGB is not premultiplied"
                edge_alpha = full[:, :, 3]
                assert np.any((edge_alpha > 0.005) & (edge_alpha < 0.15)), "no antialias coverage"
                name = f"glass_{'backdrop' if has_backdrop else 'tint'}_{scale}x.png"
                _save(full, out / name)
                verdict.append({"backdrop": has_backdrop, "scale": scale, "image": name})
            del tex, shader
    finally:
        gpu.matrix.load_projection_matrix(old_projection)
        gpu.state.blend_set(old_blend)
        gpu.state.depth_test_set(old_depth)
        gpu.state.viewport_set(*old_viewport)
    return {"backend": gpu.platform.backend_type_get(), "cases": verdict}
