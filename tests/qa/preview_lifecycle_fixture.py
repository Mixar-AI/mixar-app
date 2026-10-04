# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Main-thread QA fixture for real native preview completion/cancellation.

Load this module using importlib.util.spec_from_file_location in qa.eval.
Call hotload(worktree), setup(drv.main_window()), then start('complete').
Every call returns immediately; poll status() from separate QA requests.
Once terminal, finish('done') asserts the real RNA row, capture and settings.
Call show_origin() before taking a screenshot of the result in Agent chat.

For cancellation: start('cancel', width=2048, height=1536), click Blender's
native running-job Stop with the harness, then finish('cancelled') once done.
The monitor samples real render/reservation/row state without blocking the
event loop. assert_running() is a useful screenshot checkpoint. No paid calls.

Only transport replies are substituted. Rendering, timers, RNA step rows,
capture persistence, native cancellation and render reservations stay real.
release() restores the original response-client getter after both scenarios.
"""

import importlib
import importlib.util
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import uuid

import bpy
from mathutils import Vector

_state = {}


def hotload(worktree):
    """Load only changed Python modules into an idle isolated Dev app.

    Package paths are prepended before imports. Never reload the native
    render coordinator: its singleton reservation must remain shared.
    """
    assert not bpy.app.is_job_running('RENDER'), 'Finish the native job first'
    root = Path(worktree) / 'src/scripts'
    for name in ('mixar.modules.common.agent_execution',
                 'mixar.modules.space_mixie_chat.core'):
        package = importlib.import_module(name)
        path = str(root.joinpath(*name.split('.')))
        if path not in package.__path__:
            package.__path__.insert(0, path)
    order = (
        'mixar.modules.common.agent_execution.request',
        'mixar.modules.common.agent_execution.diagnostics',
        'mixar.modules.common.agent_execution.pump',
        'mixar.modules.space_mixie_chat.core.executor',
        'mixar.modules.space_mixie_chat.core.steps_format',
        'mixar.modules.space_mixie_chat.core.steps_recorder',
        'mixar.modules.space_mixie_chat.core.preview_deferral',
        'mixar.modules.space_mixie_chat.core.render_gate',
        'mixar.modules.space_mixie_chat.core.script_lanes',
        'mixar.modules.space_mixie_chat.core.main_thread_executor',
    )
    loaded = []
    for name in order:
        path = root.joinpath(*name.split('.')).with_suffix('.py')
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        parent, attr = name.rsplit('.', 1)
        setattr(importlib.import_module(parent), attr, module)
        loaded.append(name)
    return loaded


def _material(name, color, metallic=0.0):
    material = bpy.data.materials.new(name)
    material.diffuse_color = (*color, 1)
    material.use_nodes = True
    shader = material.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (*color, 1)
    shader.inputs['Metallic'].default_value = metallic
    shader.inputs['Roughness'].default_value = 0.3
    return material


def setup(window, device=None):
    assert os.environ.get('MIXAR_QA') == '1', 'Use an isolated QA app'
    from mixar.modules.common.render_coordinator import core as slot
    from mixar.modules.space_mixie_chat.core import jsonrpc_client
    assert not slot.busy(), 'Render slot must be idle'
    assert not _state, 'Call release or reload the fixture before setup'
    scene = bpy.data.scenes.new('QA Preview Origin')
    scene.mixie_session_id = str(uuid.uuid4())
    other = bpy.data.scenes.new('QA Preview Other Tab')
    other.mixie_session_id = str(uuid.uuid4())
    _state.update(window=window, origin=scene, other=other, replies={}, run=None,
                  real_get_client=jsonrpc_client.get_jsonrpc_client)
    window.scene = scene
    with bpy.context.temp_override(window=window, scene=scene):
        bpy.ops.mesh.primitive_plane_add(size=200)
        bpy.context.object.name = 'QA Preview Floor'
        bpy.context.object.data.materials.append(_material('QA Preview Ground', (.12, .18, .22)))
        gold = _material('QA Preview Gold', (.72, .23, .035), .65)
        for x in (-2, 0, 2):
            bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, location=(x, 0, 1))
            bpy.context.object.data.materials.append(gold)
            for polygon in bpy.context.object.data.polygons:
                polygon.use_smooth = True
        bpy.ops.object.camera_add(location=(7, -10, 6))
        scene.camera = bpy.context.object
        scene.camera.rotation_euler = (Vector((0, 0, 1)) - scene.camera.location).to_track_quat('-Z', 'Y').to_euler()
        scene.camera.data.lens = 48
        bpy.ops.object.light_add(type='AREA', location=(1, -3, 7))
        bpy.context.object.data.energy = 1800
        bpy.context.object.data.shape = 'DISK'
        bpy.context.object.data.size = 5
    scene.world = bpy.data.worlds.new('QA Preview World')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs['Color'].default_value = (.08, .12, .18, 1)
    scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = .3
    scene.render.engine = 'CYCLES'
    if device is not None:
        assert device in {'CPU', 'GPU'}, device
        scene.mixar_paint_preferences.default_render_device = device
        scene.cycles.device = device
    scene.render.resolution_x, scene.render.resolution_y = 800, 600
    scene.render.resolution_percentage = 70
    scene.cycles.samples = 128
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.use_denoising = False
    scene.render.use_lock_interface = False
    bubble = scene.mixie_chat_messages.add()
    bubble.sender = 'AGENT'
    bubble.message_type = 'AGENT'
    bubble.bubble_id = 'qa-preview-lifecycle'
    bubble.text = 'Verifying preview completion and cancellation'
    bubble.steps_collapsed = False
    bubble.images_collapsed = False
    _state['bubble_id'] = bubble.bubble_id
    def reply(request_id, result):
        assert request_id not in _state['replies'], 'Duplicate reply'
        _state['replies'][request_id] = result
        return True
    client = SimpleNamespace(is_connected=True, queue_response=reply)
    jsonrpc_client.get_jsonrpc_client = lambda: client
    return {'origin': scene.name, 'other': other.name, 'session': scene.mixie_session_id,
            'bubble': bubble.bubble_id}


def _bubble():
    return next(message for message in _state['origin'].mixie_chat_messages
                if message.bubble_id == _state['bubble_id'])


def _row():
    return next(row for row in _bubble().step_items if row.item_id == _state['run']['request'])


def start(label='complete', width=1536, height=1024, switch_tab=True, dispatch=False, inspection=None, engine='cycles'):
    from mixar.modules.common.agent_execution.request import ExecutionRequest
    from mixar.modules.common.render_coordinator import core as slot
    from mixar.modules.space_mixie_chat.core import preview_render, preview_deferral
    from mixar.modules.space_mixie_chat.core.steps_recorder import record_step_start
    assert not slot.busy()
    assert preview_deferral.get_pending_inflight() is None
    scene, window = _state['origin'], _state['window']
    window.scene = scene
    request = 'qa-preview-' + label + '-' + uuid.uuid4().hex[:8]
    req = ExecutionRequest(request, '# QA native preview', 'render_viewport', scene.mixie_session_id)
    key = uuid.uuid4().hex
    _state['run'] = {'request': request, 'key': key, 'started': time.monotonic(),
                     'samples': [], 'errors': [], 'settings': (scene.render.resolution_x,
                     scene.render.resolution_y, scene.render.resolution_percentage, scene.cycles.samples)}
    if dispatch:
        # Exercise the INSTALLED executor's early/late row handling too. Only
        # response transport is substituted, as in the direct lifecycle test.
        from mixar.modules.space_mixie_chat.core import main_thread_executor
        from mixar.modules.space_mixie_chat.core.session import SessionManager
        SessionManager.start_session(scene, 'QA native preview')
        script = ("import bpy\nfrom mixar.modules.space_mixie_chat.core import preview_render\n"
                  f"receipt = preview_render.start(bpy.context, {key!r}, width={width}, "
                  f"height={height}, engine={engine!r})\n"
                  "assert receipt['status'] == 'running', receipt\n"
                  f"__RESULT__ = {{'__deferred_preview__': {key!r}}}\n")
        if inspection is not None:
            import json
            spec = dict(inspection, width=width, height=height)
            script = ("import bpy\n"
                      f"bpy.ops.mixie_chat.agent_preview_render(job_key={key!r}, inspection_json={json.dumps(spec)!r})\n"
                      "receipt=bpy.app.driver_namespace['mixie_agent_preview_response']\n"
                      "assert receipt['status']=='running', receipt\n"
                      f"__RESULT__ = {{'__deferred_preview__': {key!r}}}\n")
        main_thread_executor.queue_script_request(script, request, 'render_viewport',
                                                  scene.mixie_session_id)
        run = _state['run']
        bpy.app.timers.register(lambda: _monitor(run), first_interval=.02)
        if switch_tab:
            window.scene = _state['other']
        return {'request': request, 'queued': True}
    record_step_start(scene, request, 'render_viewport', call_id=request)
    with bpy.context.temp_override(window=window, scene=scene):
        receipt = preview_render.start(bpy.context, key, width=width, height=height,
                                       engine=engine, inspection=inspection)
    assert receipt['status'] == 'running', receipt
    _state['run']['token'] = preview_render._job['reservation']
    preview_deferral.defer_response(req, key, scene=scene,
                                    initial_result={'success': True, '__deferred_preview__': key})
    assert _row().status == 'RUNNING'
    assert request not in _state['replies']
    assert slot.owns(_state['run']['token'])
    run = _state['run']
    bpy.app.timers.register(lambda: _monitor(run), first_interval=.02)
    if switch_tab:
        window.scene = _state['other']
    return status()


def _monitor(run):
    from mixar.modules.common.render_coordinator import core as slot
    if run is not _state['run']:
        return None
    if 'token' not in run:
        from mixar.modules.space_mixie_chat.core import preview_render
        job = preview_render._job
        if job and job['key'] == run['key']:
            run['token'] = job['reservation']
        else:
            return None if run['request'] in _state['replies'] else .02
    native = bpy.app.is_job_running('RENDER')
    reserved = slot.owns(run['token'])
    row_status = _row().status
    if native and not reserved:
        run['errors'].append('Reservation released before native teardown')
    if native and row_status != 'RUNNING':
        run['errors'].append('Step became terminal while native render was running')
    run['samples'].append((round(time.monotonic() - run['started'], 3), native, reserved, row_status))
    if run['request'] in _state['replies']:
        return None
    return .05


def status():
    from mixar.modules.common.render_coordinator import core as slot
    run = _state.get('run')
    if not run:
        return {'ready': True}
    response = _state['replies'].get(run['request'])
    rows = [row for row in _bubble().step_items if row.item_id == run['request']]
    return {'request': run['request'], 'native_running': bpy.app.is_job_running('RENDER'),
            'reserved': slot.owns(run.get('token')), 'row': rows[0].status if rows else None,
            'terminal': response is not None, 'success': response.get('success') if response else None,
            'result_status': response.get('status') if response else None,
            'response_error': response.get('error') if response else None,
            'captures': [item.local_path for item in _bubble().image_items if item.step_id == run['request']],
            'foreground': _state['window'].scene.name, 'samples': len(run['samples']),
            'render': response.get('render') if response else None,
            'elapsed_s': round(time.monotonic() - run['started'], 3), 'errors': list(run['errors'])}


def assert_running():
    value = status()
    assert value['native_running'] and value['reserved'], value
    assert value['row'] == 'RUNNING' and not value['terminal'], value
    return value


def finish(expected='done'):
    value = status()
    assert value['terminal'] and not value['native_running'] and not value['reserved'], value
    assert value['result_status'] == expected, value
    assert value['success'] is (expected == 'done'), value
    assert value['row'] == ('DONE' if expected == 'done' else 'FAILED'), value
    assert not value['errors'] and value['samples'] > 0, value
    if expected == 'done':
        assert value['captures'] and all(Path(path).is_file() for path in value['captures']), value
    else:
        assert not value['captures'], value
    assert not any(row.item_id == value['request'] for message in _state['other'].mixie_chat_messages
                   for row in message.step_items), 'Completion leaked to the other tab'
    scene = _state['origin']
    actual = (scene.render.resolution_x, scene.render.resolution_y,
              scene.render.resolution_percentage, scene.cycles.samples)
    assert actual == _state['run']['settings'], (actual, _state['run']['settings'])
    return {**value, 'restored_settings': actual, 'monitor_samples': _state['run']['samples']}


def show_origin():
    _state['window'].scene = _state['origin']
    from mixar.modules.space_mixie_chat.core.ui_utils import bump_layout_epoch, redraw_chat_areas
    bump_layout_epoch(_state['origin'])
    redraw_chat_areas()
    return status()


def release():
    from mixar.modules.common.render_coordinator import core as slot
    from mixar.modules.space_mixie_chat.core import jsonrpc_client
    assert not slot.busy(), 'Stop or finish the native job before restoring transport'
    jsonrpc_client.get_jsonrpc_client = _state['real_get_client']
    from mixar.modules.space_mixie_chat.core.session import SessionManager
    from mixar.modules.space_mixie_chat.constants import SessionState
    SessionManager.set_state(_state['origin'], SessionState.IDLE)
    return {'restored_transport': True}
