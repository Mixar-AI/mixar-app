# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Temporary delivery settings, preserving scene quality and user edits."""

class Settings:
    def __init__(self, scene):
        self.scene = scene
        self.values = []
        self.frame = scene.frame_current
        self.subframe = scene.frame_subframe
        image = scene.render.image_settings
        self.image_original = {k: getattr(image, k) for k in
                               ("media_type", "file_format", "color_mode", "color_depth")}
        self.image_applied = None

    def set(self, owner, name, value):
        original = getattr(owner, name)
        if original != value:
            self.values.append((owner, name, original, value))
            setattr(owner, name, value)

    def apply(self, kind, path, engine="", samples=0, width=0, height=0,
              frame_start=None, frame_end=None, fps=0, max_faces=0):
        scene, r = self.scene, self.scene.render
        if engine:
            self.set(r, "engine", {"eevee": "BLENDER_EEVEE", "cycles": "CYCLES"}[engine])
        from mixar.modules.common.render_coordinator.core.geometry_budget import downgrade_over_budget
        self.downgraded = downgrade_over_budget(scene, self.set, max_faces)
        if samples:
            owner = scene.cycles if r.engine == 'CYCLES' else scene.eevee
            name = 'samples' if r.engine == 'CYCLES' else 'taa_render_samples'
            if hasattr(owner, name):
                self.set(owner, name, samples)
        if width:
            self.set(r, "resolution_x", width)
            self.set(r, "resolution_y", height)
            self.set(r, "resolution_percentage", 100)
        image = r.image_settings
        try:
            image.media_type = 'VIDEO' if kind == 'video' else 'IMAGE'
            image.file_format = 'FFMPEG' if kind == 'video' else 'PNG'
            if kind == 'video':
                image.color_mode, image.color_depth = 'RGB', '8'
        finally:
            self.image_applied = {k: getattr(image, k) for k in self.image_original}
        if kind == 'video':
            self.set(r, "filepath", path)
            self.set(r, "use_file_extension", True)
            self.set(r.ffmpeg, "format", 'MPEG4')
            self.set(r.ffmpeg, "codec", 'H264')
            self.set(r.ffmpeg, "constant_rate_factor", 'MEDIUM')
            if frame_start is not None:
                self.set(scene, "frame_start", frame_start)
                self.set(scene, "frame_end", frame_end)
            if fps:
                self.set(r, "fps", fps)
                self.set(r, "fps_base", 1.0)

    def restore(self, last_frame=None):
        for owner, name, original, applied in reversed(self.values):
            try:
                if getattr(owner, name) == applied:
                    setattr(owner, name, original)
            except (ReferenceError, RuntimeError, AttributeError):
                pass
        try:
            image = self.scene.render.image_settings
            if self.image_applied and all(getattr(image, k) == v
                                          for k, v in self.image_applied.items()):
                # Blender filters file_format by media_type; restore in that order.
                for name, value in self.image_original.items():
                    setattr(image, name, value)
            if last_frame is not None and self.scene.frame_current == last_frame:
                self.scene.frame_set(self.frame, subframe=self.subframe)
        except (ReferenceError, RuntimeError):
            pass


def render_info(scene):
    r = scene.render
    return {"engine": r.engine,
            "width": int(r.resolution_x * r.resolution_percentage / 100),
            "height": int(r.resolution_y * r.resolution_percentage / 100),
            "samples": int(scene.cycles.samples) if r.engine == 'CYCLES' else
                       int(getattr(scene.eevee, 'taa_render_samples', 0)),
            "device": scene.cycles.device if r.engine == 'CYCLES' else 'engine_default',
            "frame_start": scene.frame_start, "frame_end": scene.frame_end,
            "frame_step": scene.frame_step, "fps": r.fps / r.fps_base}
