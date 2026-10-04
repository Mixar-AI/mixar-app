# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Temporary inspection rig owned by the native preview job until teardown."""
import math

import bpy
from mathutils import Vector

from .inspection_bounds import (
    _bounds_dict, _find_enclosing_shells, _resolve_focus, _world_aabb,
    _project_labels, _z_ranges, _instance_corners,
)


class Inspection:
    def __init__(self, scene, params, set_value):
        self.scene = scene
        self.params = params
        self.set = set_value
        self.created = []
        self.metadata = {}
        self.instances = {}

    def _camera(self, original=None):
        data = original.data.copy() if original else bpy.data.cameras.new('_rv_cam')
        self.created.append((bpy.data.cameras, data))
        obj = bpy.data.objects.new('_rv_cam', data)
        self.created.append((bpy.data.objects, obj))
        self.scene.collection.objects.link(obj)
        if original:
            obj.matrix_world = original.matrix_world.copy()
        self.set(self.scene, 'camera', obj)
        return obj

    def prepare(self, context):
        p, scene = self.params, self.scene
        view = str(p.get('view', 'camera'))
        shading = str(p.get('shading', 'material'))
        if shading not in {'solid', 'material'} or p.get('engine') in {'splat', 'kiri', 'gaussian', '3dgs'}:
            raise ValueError('inspection_mode_unsupported')
        if view not in {'camera', 'hero', 'top', 'front'} and not view.startswith('mark:'):
            raise ValueError('inspection_view_unsupported')
        from .preview_render import _apply_resolution
        _apply_resolution(scene.render, self.set, int(p.get('width', 1024)), int(p.get('height', 768)))
        self.set(scene.render, 'resolution_percentage', 100)
        self.instances = _instance_corners(context, scene)
        content = [o for o in scene.objects if o.type in {
            'MESH', 'CURVE', 'SURFACE', 'FONT', 'META', 'VOLUME', 'POINTCLOUD',
            'CURVES', 'GREASEPENCIL', 'GPENCIL'} and o.visible_get()]
        shells = _find_enclosing_shells([o for o in content if o.type == 'MESH']) if p.get('hide_shells') else []
        content.extend(o for o in self.instances if o not in content)
        for obj in shells:
            self.set(obj, 'hide_render', True)
        content = [o for o in content if o not in set(shells)]
        focus, report = [], None
        if p.get('focus_objects'):
            touching_enabled = bool(p.get('include_touching', True))
            focus, touching, missing = _resolve_focus(content, p['focus_objects'], touching_enabled, .01, self.instances)
            if not focus:
                raise ValueError('inspection_focus_not_found')
            shown = set(focus) | set(touching)
            hidden = [o for o in content if o not in shown]
            for obj in hidden:
                self.set(obj, 'hide_render', True)
            content = [o for o in content if o in shown]
            report = {'objects': _z_ranges(focus, self.instances), 'touching': _z_ranges(touching, self.instances),
                      'bounds': _bounds_dict(_world_aabb(focus, self.instances)),
                      'touching_bounds': _bounds_dict(_world_aabb(touching, self.instances)),
                      'missing': missing, 'hidden': len(hidden),
                      'include_touching': touching_enabled, 'tolerance_m': .01}
        mark = view.startswith('mark:')
        camera = scene.camera
        auto_frame = view != 'camera' or camera is None or bool(focus or p.get('focus_point'))
        if mark:
            original = bpy.data.objects.get(view[5:].strip())
            if original is None or original.type != 'CAMERA':
                raise ValueError('inspection_mark_unavailable')
            camera = self._camera(original)
        elif view != 'camera' or camera is None:
            camera = self._camera()
            camera.rotation_euler = ((0, 0, 0) if view == 'top' else
                                     (math.pi / 2, 0, 0) if view == 'front' else (1.30, 0, .785))
        elif focus or p.get('focus_point'):
            # Frame a private copy, preserving all user camera animation/constraints.
            camera = self._camera(camera)
        context.view_layer.update()
        center = radius = None
        if not mark:
            point = p.get('focus_point')
            if point:
                center = Vector(tuple(float(v) for v in point))
                radius = max(.0005, float(p.get('focus_radius', 12)))
            elif focus or content:
                box = _world_aabb(focus or content, self.instances)
                center = (box[0] + box[1]) / 2
                radius = max(.0005, (box[1] - box[0]).length / 2) * (1.2 if focus else 1)
        if center is not None and auto_frame:
            direction = (camera.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized()
            # Use Blender's actual gate: sensor fit, portrait/landscape and pixel
            # aspect all affect the narrower FOV. camera.data.angle alone clips
            # wide inspection frames vertically.
            frame = camera.data.view_frame(scene=scene)
            tangent = min(max(abs(v.x/v.z) for v in frame), max(abs(v.y/v.z) for v in frame))
            fov = 2 * math.atan(tangent)
            distance = radius / max(math.sin(fov / 2), .001) * 1.15
            camera.location = center - direction * distance
            if camera.data.type == 'ORTHO':
                half_gate = min(max(abs(v.x) for v in frame), max(abs(v.y) for v in frame))
                camera.data.ortho_scale *= radius * 1.15 / max(half_gate, 1e-9)
            camera.data.clip_start = max(.00001, (distance - radius) * .5)
            camera.data.clip_end = distance + radius * 3 + 100
        # EEVEE's first shader compilation can hold the shared graphics context
        # and stall UI drawing even with INVOKE_DEFAULT. Cycles' render job does
        # its material work off the UI thread, on the user's configured device.
        engine = 'BLENDER_WORKBENCH' if shading == 'solid' else 'CYCLES'
        self.set(scene.render, 'engine', engine)
        if shading == 'solid':
            self.set(scene.display.shading, 'color_type', 'MATERIAL')
            self.set(scene.display, 'render_aa', '5')
        else:
            self.set(scene.cycles, 'samples', 8)
            self.set(scene.cycles, 'use_denoising', True)
            world = bpy.data.worlds.new('_rv_world')
            self.created.append((bpy.data.worlds, world))
            world.use_nodes = True
            background = world.node_tree.nodes.get('Background')
            background.inputs[0].default_value = (.8, .8, .8, 1)
            background.inputs[1].default_value = .6
            self.set(scene, 'world', world)
            light = bpy.data.lights.new('_rv_sun', 'SUN')
            self.created.append((bpy.data.lights, light))
            light.energy = 4
            obj = bpy.data.objects.new('_rv_sun', light)
            self.created.append((bpy.data.objects, obj))
            scene.collection.objects.link(obj)
            obj.rotation_euler = (math.radians(52), math.radians(8), math.radians(40))
        context.view_layer.update()
        self.metadata = {'success': True, 'hidden_shells': sorted(o.name for o in shells),
                         'focus': report, 'objects': [], 'capture_method': 'native_async',
                         'mark_camera_used': mark, 'capture_attempts': ['native_async'],
                         'engine': engine, 'object_id_palette': []}

    def finish(self, result):
        if result.get('status') == 'done':
            result.update(self.metadata)
            result['engine'] = result['render']['engine']
            result['objects'] = _project_labels(self.scene, result['render']['width'], result['render']['height'], self.instances)
            result.update(image_base64=result.pop('image_url').split(',', 1)[1],
                          image_mime='image/png', width=result['render']['width'],
                          height=result['render']['height'])
        else:
            result['success'] = False
            result.setdefault('error', 'inspection_preview_' + result.get('status', 'failed'))

    def cleanup(self):
        for collection, item in reversed(self.created):
            try:
                collection.remove(item, do_unlink=True)
            except (ReferenceError, RuntimeError):
                pass
        self.created.clear()
