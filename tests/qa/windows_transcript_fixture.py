# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Solid GPU backdrop for testing native Windows transcript compositing."""


def install():
    import bpy
    import gpu
    from gpu_extras.batch import batch_for_shader

    assert __import__('os').environ.get('MIXAR_QA') == '1'
    state = {'value': 1.0, 'draws': 0}
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')

    def draw():
        r = bpy.context.region
        batch = batch_for_shader(shader, 'TRI_FAN', {'pos': (
            (0, 0), (r.width, 0), (r.width, r.height), (0, r.height))})
        gpu.state.blend_set('NONE')
        shader.bind()
        shader.uniform_float('color', (state['value'],) * 3 + (1.0,))
        batch.draw(shader)
        state['draws'] += 1

    state['handler'] = bpy.types.SpaceView3D.draw_handler_add(draw, (), 'WINDOW', 'POST_PIXEL')
    bpy.app.driver_namespace['qa_transcript_backdrop'] = state
    return True


def remove():
    import bpy

    state = bpy.app.driver_namespace.pop('qa_transcript_backdrop', None)
    if state:
        bpy.types.SpaceView3D.draw_handler_remove(state['handler'], 'WINDOW')
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            a.tag_redraw()
