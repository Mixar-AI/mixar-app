# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Deliberately small, explicit quick controls; never enumerate arbitrary RNA."""

# Two or three high-impact controls per type. Simulation and mode-dependent
# controls below have their own handling. Engine Mode retains the full editor.
QUICK_FIELDS = {
    'BEVEL': ('width', 'segments'),
    'SUBSURF': ('levels', 'render_levels'),
    'MIRROR': ('use_axis', 'use_clip', 'mirror_object'),
    'ARRAY': ('count', 'relative_offset_displace'),
    'SOLIDIFY': ('thickness', 'offset'),
    'TRIANGULATE': ('quad_method',),
    'WELD': ('merge_threshold',),
    'EDGE_SPLIT': ('split_angle',),
    'BUILD': ('frame_start', 'frame_duration'),
    'MASK': ('vertex_group', 'invert_vertex_group'),
    'WIREFRAME': ('thickness', 'use_replace'),
    'SCREW': ('axis', 'angle', 'screw_offset'),
    'DISPLACE': ('texture', 'strength', 'mid_level'),
    'SMOOTH': ('factor', 'iterations'),
    'LAPLACIANSMOOTH': ('lambda_factor', 'iterations'),
    'CORRECTIVE_SMOOTH': ('factor', 'iterations'),
    'SMOOTH_BY_ANGLE': ('angle',),
    'LAPLACIANDEFORM': ('vertex_group',),
    'HOOK': ('object', 'strength'),
    'SKIN': ('branch_smoothing', 'use_smooth_shade'),
    'CAST': ('cast_type', 'factor', 'object'),
    'CURVE': ('object', 'deform_axis'),
    'ARMATURE': ('object', 'use_deform_preserve_volume'),
    'LATTICE': ('object', 'strength'),
    'MESH_DEFORM': ('object',),
    'SURFACE_DEFORM': ('target', 'strength'),
    'SHRINKWRAP': ('target', 'offset', 'wrap_method'),
    'WAVE': ('height', 'width', 'speed'),
    'WARP': ('object_from', 'object_to', 'strength'),
    'WEIGHTED_NORMAL': ('weight', 'keep_sharp'),
    'NORMAL_EDIT': ('mode', 'target', 'mix_factor'),
    'DATA_TRANSFER': ('object', 'mix_factor'),
    'UV_PROJECT': ('uv_layer',),
    'UV_WARP': ('object_from', 'object_to', 'uv_layer'),
    'VERTEX_WEIGHT_EDIT': ('vertex_group', 'default_weight'),
    'VERTEX_WEIGHT_MIX': ('vertex_group_a', 'vertex_group_b', 'mix_mode'),
    'VERTEX_WEIGHT_PROXIMITY': ('vertex_group', 'target'),
    'MESH_CACHE': ('filepath', 'factor'),
    'MESH_SEQUENCE_CACHE': ('cache_file', 'object_path'),
    'MULTIRES': ('levels', 'render_levels'),
    'VOLUME_DISPLACE': ('texture', 'strength'),
    'VOLUME_TO_MESH': ('object', 'threshold'),
    'PARTICLE_INSTANCE': ('object', 'particle_system_index'),
    'EXPLODE': ('use_edge_cut',),
    'OCEAN': ('wave_scale', 'choppiness', 'time'),
    'FLUID': ('fluid_type',),
    'DYNAMIC_PAINT': ('ui_type',),
}


def _fields(layout, data, names):
    for name in names:
        if hasattr(data, name):
            layout.prop(data, name)


def draw_modifier_properties(layout, modifier):
    layout.context_pointer_set("modifier", modifier)
    layout.label(text=modifier.name, icon='MODIFIER')
    kind = modifier.type
    if kind == 'CLOTH':
        cloth = modifier.settings
        body = layout.column()
        body.enabled = not modifier.point_cache.is_baked
        body.prop(cloth, 'mass', text="Weight")
        body.prop(cloth, 'vertex_group_mass', text="Pin Group")
        body.prop(modifier.collision_settings, 'use_self_collision', text="Self Collision")
        return
    if kind == 'PARTICLE_SYSTEM':
        system = modifier.particle_system
        settings = system.settings if system else None
        if settings:
            body = layout.column()
            body.enabled = settings.is_editable and not system.point_cache.is_baked
            body.prop(settings, 'count', text="Count")
            if settings.type == 'HAIR':
                body.prop(settings, 'hair_length', text="Length")
            else:
                body.prop(settings, 'lifetime', text="Lifetime")
                body.prop(settings, 'normal_factor', text="Speed")
        return
    if kind == 'BOOLEAN':
        layout.prop(modifier, 'operation', text="Operation")
        prop = 'collection' if modifier.operand_type == 'COLLECTION' else 'object'
        layout.prop(modifier, prop, text="Target")
        return
    if kind == 'DECIMATE':
        layout.prop(modifier, 'decimate_type', text="Method")
        _fields(layout, modifier, ({'COLLAPSE': 'ratio', 'UNSUBDIV': 'iterations',
                                   'DISSOLVE': 'angle_limit'}[modifier.decimate_type],))
        return
    if kind == 'REMESH':
        layout.prop(modifier, 'mode', text="Method")
        _fields(layout, modifier, ('voxel_size',) if modifier.mode == 'VOXEL'
                else ('octree_depth', 'scale'))
        return
    if kind == 'SIMPLE_DEFORM':
        layout.prop(modifier, 'deform_method', text="Method")
        layout.prop(modifier, 'deform_axis', text="Axis")
        layout.prop(modifier, 'angle' if modifier.deform_method in {'TWIST', 'BEND'} else 'factor')
        return
    if kind == 'COLLISION':
        _fields(layout, modifier.settings, ('thickness_outer', 'cloth_friction'))
        return
    if kind == 'SOFT_BODY':
        _fields(layout, modifier.settings, ('mass', 'friction'))
        return
    if kind == 'NODES':
        layout.template_ID(modifier, 'node_group')
        layout.label(text="Edit node inputs in Engine Mode.", icon='INFO')
        return
    fields = QUICK_FIELDS.get(kind)
    if fields:
        _fields(layout, modifier, fields)
        if kind in {'MESH_DEFORM', 'SURFACE_DEFORM', 'LAPLACIANDEFORM', 'MULTIRES',
                    'DATA_TRANSFER', 'UV_PROJECT', 'FLUID', 'DYNAMIC_PAINT'}:
            layout.label(text="Complete setup in Engine Mode.", icon='INFO')
    else:
        layout.label(text="Edit settings in Engine Mode.", icon='INFO')


classes = ()
