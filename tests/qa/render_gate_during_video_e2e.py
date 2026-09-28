# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Agent scripts during a scene video render: no paid calls, no backend needed.

Replays the 4.1.1 crash (render-thread SIGSEGV in
graph_tag_ids_for_visible_update): while a scene_render video renders on the
job thread, a burst of moodboard inspections and the agent's material-swap +
frame_set script go through the REAL main-thread executor queue. Inspections
must answer with JPEGs and create no datablock; the edit must be refused with
render_in_progress and change nothing; the video must still land on Moodboard;
after it, the same edit must run.

The inspection script is the backend's own build_inspect_script when
MIXAR_BACKEND (default ../mixar-backend) has a .venv, else an equivalent copy.
QA_HARNESS, MIXAR_QA_PORT, QA_SCENARIO_OUT select harness, app and evidence.
"""
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, ensure_moodboard_area, run_scenario  # noqa: E402

KEY = '5' * 32
INSPECTIONS = 12
BOARD = ('qa_gate_a.jpg', 'qa_gate_b.jpg', 'qa_gate_c.jpg')

_FALLBACK_INSPECT = '''import bpy, base64, json
from mixar.modules.space_mixie_chat.core.attachment_compression import encode_blend_image_jpeg
__img = bpy.data.images.get({name!r})
__data = encode_blend_image_jpeg(__img, 1024)
print('__RESULT__' + json.dumps({{'success': True, 'mime': 'image/jpeg',
    'image_base64': base64.b64encode(__data).decode('ascii'),
    'width': __img.size[0], 'height': __img.size[1]}}))
'''

# The agent's script at 04:23:39 in the crash trace, four seconds into the render.
_EDIT = '''import bpy
cube = bpy.data.objects['Cube']
cube.data.materials[0] = bpy.data.materials['QA Gate Clay']
bpy.context.scene.frame_set(1)
'''

SETUP = '''
import os, tempfile
from PIL import Image as PILImage
assert os.environ.get('MIXAR_QA') == '1'
from mixar.modules.common.utils.image_utils import add_image_to_moodboard
with bpy.context.temp_override(window=drv.main_window()):
    scene = bpy.context.scene
    if not scene.mixie_session_id:
        scene.mixie_session_id = '22222222-2222-4222-8222-222222222222'
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x, scene.render.resolution_y = 640, 480
    scene.render.resolution_percentage = 100
    scene.eevee.taa_render_samples = 32
    scene.frame_start, scene.frame_end = 1, 96
    scene.render.fps = 24
    cube = scene.objects.get('Cube')
    assert cube is not None and scene.camera is not None
    cube.animation_data_clear()
    cube.rotation_euler.z = 0.0
    cube.keyframe_insert(data_path='rotation_euler', index=2, frame=1)
    cube.rotation_euler.z = 6.2832
    cube.keyframe_insert(data_path='rotation_euler', index=2, frame=97)
    red = bpy.data.materials.get('QA Gate Red') or bpy.data.materials.new('QA Gate Red')
    # Base colours, not just viewport colours: a leaked clay frame must show in the video.
    for mat, color in ((red, (0.8, 0.03, 0.02, 1)),
                       (bpy.data.materials.get('QA Gate Clay') or bpy.data.materials.new('QA Gate Clay'),
                        (0.6, 0.6, 0.6, 1))):
        mat.diffuse_color = color
        mat.use_nodes = True
        mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = color
    cube.data.materials.clear()
    cube.data.materials.append(red)
    scene.frame_set(40)
    folder = tempfile.mkdtemp(prefix='qa_render_gate_')
    for index, name in enumerate(BOARD):
        if bpy.data.images.get(name):
            continue
        path = os.path.join(folder, name)
        noise = PILImage.frombytes('RGB', (32, 24), os.urandom(32 * 24 * 3))
        noise.resize((1600 + index * 200, 1200), PILImage.BILINEAR).save(path, quality=90)
        image = bpy.data.images.load(path)
        image.name = name
        image.pack()
        add_image_to_moodboard(image, prompt='qa gate reference')
    ns = bpy.app.driver_namespace
    ns['qa_gate_frame'] = scene.frame_current
    ns['qa_gate_items'] = len(scene.mixie_moodboard_images)
result = {'scene': scene.name, 'items': len(scene.mixie_moodboard_images),
          'session': scene.mixie_session_id}
'''.replace('BOARD', repr(BOARD))

START = f'''
from mixar.modules.scene_render.core import jobs
from mixar.modules.common.render_coordinator import core as slot
from mixar.modules.space_mixie_chat.core.executor import ScriptExecutor
script = ("bpy.ops.mixar.scene_render_start(job_key={KEY!r}, kind='video', label='QA Gate Video')\\n"
          "print('__RESULT__' + json.dumps(bpy.app.driver_namespace['mixar_scene_render_response']))")
with bpy.context.temp_override(window=drv.main_window()):
    ScriptExecutor().execute(script)
    receipt = bpy.app.driver_namespace['mixar_scene_render_response']
assert receipt['status'] == 'started', receipt
assert bpy.app.is_job_running('RENDER')
assert slot.native_render_kind() == 'scene_video', slot.native_render_kind()
result = receipt
'''

# Replies go to an in-app fake client, so no backend or login is needed; the
# executor only runs scripts for an active session, so mark the tab busy.
CAPTURE = '''
from types import SimpleNamespace
from mixar.modules.space_mixie_chat.core import jsonrpc_client
from mixar.modules.space_mixie_chat.core.session import get_session_manager
from mixar.modules.space_mixie_chat.constants import SessionState
ns = bpy.app.driver_namespace
ns['qa_gate'] = {}
if 'qa_gate_real_client' not in ns:
    ns['qa_gate_real_client'] = jsonrpc_client.get_jsonrpc_client
fake = SimpleNamespace(is_connected=True,
                       queue_response=lambda rid, res: ns['qa_gate'].__setitem__(rid, res))
jsonrpc_client.get_jsonrpc_client = lambda: fake
get_session_manager().set_state(drv.main_window().scene, SessionState.BUSY)
result = True
'''

RELEASE = '''
from mixar.modules.space_mixie_chat.core import jsonrpc_client
from mixar.modules.space_mixie_chat.core.session import get_session_manager
from mixar.modules.space_mixie_chat.constants import SessionState
real = bpy.app.driver_namespace.pop('qa_gate_real_client', None)
if real is not None:
    jsonrpc_client.get_jsonrpc_client = real
get_session_manager().set_state(drv.main_window().scene, SessionState.IDLE)
result = True
'''


def _inspect_script(name):
    backend = Path(os.environ.get('MIXAR_BACKEND', Path(__file__).resolve().parents[3] / 'mixar-backend'))
    python = backend / '.venv/bin/python'
    if python.exists():
        code = ('import sys; from modules.agent.tools.domains.moodboard import build_inspect_script; '
                'sys.stdout.write(build_inspect_script(sys.argv[1]))')
        out = subprocess.run([str(python), '-c', code, name], cwd=backend, capture_output=True,
                             text=True, check=True).stdout
        if 'encode_blend_image_jpeg' not in out:
            raise ScenarioFail('backend inspect script does not use the datablock-free encoder')
        return out
    return _FALLBACK_INSPECT.format(name=name)


def _enqueue(session, jobs):
    lines = ['from mixar.modules.space_mixie_chat.core.main_thread_executor import queue_script_request']
    for rid, tool, script in jobs:
        lines.append(f"queue_script_request({script!r}, {rid!r}, {tool!r}, {session!r}, "
                     f"{{'chat_session_id': {session!r}, 'turn_id': 'qa-gate'}})")
    lines.append('result = True')
    return '\n'.join(lines)


def run(qa):
    output = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/render-gate-evidence')).resolve()
    output.mkdir(parents=True, exist_ok=True)
    qa.step('reset', qa.cmd, 'reset_state')
    qa.step('dismiss_splash', qa.dismiss_splash)
    qa.step('moodboard_visible', ensure_moodboard_area, qa, sidebar=False)
    setup = qa.step('setup', qa.eval, SETUP)
    session = setup['session']
    scripts = {name: _inspect_script(name) for name in BOARD}
    burst = [(f'qa-gate-inspect-{n}', 'inspect_moodboard_image', scripts[BOARD[n % len(BOARD)]])
             for n in range(INSPECTIONS)]
    burst.insert(INSPECTIONS // 2, ('qa-gate-edit', 'execute_bpy_script', _EDIT))
    qa.step('capture_replies', qa.eval, CAPTURE)
    try:
        qa.step('video_start_receipt', qa.eval, START)
        # After the start: the render itself adds 'Render Result'.
        images_before = qa.eval('result = sorted(bpy.data.images.keys())')
        qa.step('enqueue_burst_during_render', qa.eval, _enqueue(session, burst))
        qa.step('burst_answered', qa.wait,
                f"len(bpy.app.driver_namespace.get('qa_gate', {{}})) == {len(burst)}", timeout=90)
        during = qa.step('answers_during_render', qa.eval, '''
import base64, io, json
from PIL import Image as PILImage
ns = bpy.app.driver_namespace
replies = ns['qa_gate']
alive = bpy.app.is_job_running('RENDER')
edit = replies['qa-gate-edit']
assert edit['success'] is False and edit['error_type'] == 'render_in_progress', edit
assert edit['render_kind'] == 'scene_video', edit
cube = bpy.data.objects['Cube']
assert cube.data.materials[0].name == 'QA Gate Red', cube.data.materials[0].name
sizes = []
for rid, reply in sorted(replies.items()):
    if rid == 'qa-gate-edit':
        continue
    assert reply.get('success'), (rid, reply)
    out = reply.get('output', '')
    payload = json.loads(out[out.index('__RESULT__') + 10:].splitlines()[0])
    assert payload['success'] and payload['mime'] == 'image/jpeg', payload.get('error')
    jpeg = PILImage.open(io.BytesIO(base64.b64decode(payload['image_base64'])))
    assert jpeg.format == 'JPEG' and max(jpeg.size) == 1024, jpeg.size
    sizes.append(jpeg.size)
result = {'render_alive': alive, 'edit': edit, 'inspections': len(sizes), 'sizes': sorted(set(sizes)),
          'images': sorted(bpy.data.images.keys())}
''')
        if not during['render_alive']:
            raise ScenarioFail('render finished before the burst was answered; raise the frame count')
        if during['images'] != images_before:
            raise ScenarioFail(f"inspection created datablocks: {set(during['images']) - set(images_before)}")
        qa.step('during_render', qa.snap, str(output / 'during-render.png'))
        qa.step('video_completes', qa.wait,
                f"bpy.app.driver_namespace.get('mixar_scene_render_results', {{}}).get({KEY!r}, {{}})"
                ".get('status') != 'started'", timeout=600)
        video = qa.step('video_on_moodboard', qa.eval, f'''
ns = bpy.app.driver_namespace
receipt = ns['mixar_scene_render_results'][{KEY!r}]
assert receipt['status'] == 'done', receipt
scene = drv.main_window().scene
item = scene.mixie_moodboard_images[-1]
assert item.image.source == 'MOVIE' and item.image.frame_duration == 96, item.image.frame_duration
assert len(scene.mixie_moodboard_images) == ns['qa_gate_items'] + 1
assert scene.frame_current == ns['qa_gate_frame'], scene.frame_current
assert not bpy.app.is_job_running('RENDER')
result = {{'receipt': receipt, 'frames': item.image.frame_duration}}
''')
        qa.step('video_visible', qa.snap, str(output / 'video-moodboard.png'))
        qa.step('enqueue_edit_after_render', qa.eval, _enqueue(session, [('qa-gate-after', 'execute_bpy_script', _EDIT)]))
        qa.step('edit_answered', qa.wait, "'qa-gate-after' in bpy.app.driver_namespace['qa_gate']", timeout=30)
        after = qa.step('edit_runs_after_render', qa.eval, '''
reply = bpy.app.driver_namespace['qa_gate']['qa-gate-after']
assert reply.get('success') is True, reply
cube = bpy.data.objects['Cube']
assert cube.data.materials[0].name == 'QA Gate Clay'
cube.data.materials[0] = bpy.data.materials['QA Gate Red']
result = {'success': reply['success']}
''')
    finally:
        qa.step('release', qa.eval, RELEASE)
    return {'during': {k: during[k] for k in ('render_alive', 'inspections', 'sizes')},
            'refusal': during['edit'], 'video': video, 'after': after, 'output': str(output)}


if __name__ == '__main__':
    run_scenario('render_gate_during_video', run)
