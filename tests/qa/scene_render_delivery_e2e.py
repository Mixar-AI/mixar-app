# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real still/video Moodboard delivery, no paid calls unless QA_RENDER_AGENT=1.

Requires an isolated QA profile and current installed Python. Optional agent
case spends two short chat turns on the backend configured in the QA build.
QA_HARNESS, MIXAR_QA_PORT, QA_SCENARIO_OUT select harness, app and evidence.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario, ensure_moodboard_area

SETUP = '''
import os
assert os.environ.get('MIXAR_QA') == '1'
assert 'qa-p' in os.environ['MIXAR_USER_RESOURCES']
from mixar.modules.scene_render.core import jobs
from mixar.modules.common.render_coordinator import core as slot
from mixar.modules.space_mixie_chat.core.executor import ScriptExecutor
with bpy.context.temp_override(window=drv.main_window()):
    scene = bpy.context.scene
    if not scene.mixie_session_id:
        scene.mixie_session_id = '11111111-1111-4111-8111-111111111111'
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = 320
    scene.render.resolution_y = 240
    scene.render.resolution_percentage = 100
    scene.eevee.taa_render_samples = 8
    scene.render.image_settings.media_type = 'IMAGE'
    scene.render.image_settings.file_format = 'JPEG'
    scene.frame_start, scene.frame_end = 1, 6
    scene.render.fps = 12
    scene.frame_set(3)
    cube = scene.objects.get('Cube')
    assert cube is not None and scene.camera is not None
    cube.location.x = -0.6
    cube.keyframe_insert(data_path='location', frame=1)
    cube.location.x = 0.6
    cube.keyframe_insert(data_path='location', frame=6)
    mat = bpy.data.materials.new('QA Red')
    mat.diffuse_color = (0.8, 0.025, 0.015, 1)
    mat.use_nodes = True
    mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value = mat.diffuse_color
    cube.data.materials.clear()
    cube.data.materials.append(mat)
    scene.frame_set(3)
    bpy.app.driver_namespace['qa_render_scene'] = scene.name
    bpy.app.driver_namespace['qa_render_count'] = len(scene.mixie_moodboard_images)
    bpy.app.driver_namespace['qa_render_frame'] = scene.frame_current
result = {'scene': scene.name, 'items': len(scene.mixie_moodboard_images)}
'''


def start_code(key, kind, label, switch_scene=False):
    script = (f"bpy.ops.mixar.scene_render_start(job_key={key!r}, kind={kind!r}, label={label!r})\n"
              "print('__RESULT__' + json.dumps(bpy.app.driver_namespace['mixar_scene_render_response']))")
    code = f'''
from mixar.modules.scene_render.core import jobs
from mixar.modules.space_mixie_chat.core.executor import ScriptExecutor
with bpy.context.temp_override(window=drv.main_window()):
    reply = ScriptExecutor().execute({script!r})
    receipt = bpy.app.driver_namespace['mixar_scene_render_response']
    assert receipt['status'] == 'started', (reply, receipt)
    assert jobs._complete in bpy.app.handlers.render_complete
    assert jobs._cancel in bpy.app.handlers.render_cancel
    assert jobs._write in bpy.app.handlers.render_write
    assert jobs._before_load in bpy.app.handlers.load_pre
    assert jobs._job is not None
result = receipt
'''
    if switch_scene:
        code += "\nassert jobs._job is not None\nother = bpy.data.scenes.new('QA Other Scene')\ndrv.main_window().scene = other\n"
    return code


def run(qa):
    output = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/scene-render-evidence')).resolve()
    output.mkdir(parents=True, exist_ok=True)
    qa.step('login', qa.cmd, 'wait_login', timeout=60)
    qa.step('reset', qa.cmd, 'reset_state')
    qa.step('reconnect', qa.cmd, 'wait_login', timeout=60)
    qa.step('dismiss_splash', qa.dismiss_splash)
    qa.step('moodboard_visible', ensure_moodboard_area, qa)
    qa.step('setup', qa.eval, SETUP)
    qa.step('before', qa.snap, str(output / 'before.png'))
    qa.step('image_start_receipt', qa.eval, start_code('1' * 32, 'image', 'QA Scene Image', switch_scene=True))
    qa.step('during_render', qa.snap, str(output / 'image-started.png'))
    qa.step('scene_switch_during_render', qa.eval, '''
assert drv.main_window().scene.name == 'QA Other Scene'
result = True
''')
    qa.step('image_completes', qa.wait,
            "bpy.app.driver_namespace.get('mixar_scene_render_results', {}).get('" + '1' * 32 + "', {}).get('status') != 'started'",
            timeout=60)
    image = qa.step('image_on_origin_and_replay', qa.eval, '''
from mixar.modules.scene_render.core import jobs
from mixar.modules.common.render_coordinator import core as slot
origin = bpy.data.scenes[bpy.app.driver_namespace['qa_render_scene']]
assert not drv.main_window().scene.mixie_moodboard_images
assert len(origin.mixie_moodboard_images) == bpy.app.driver_namespace['qa_render_count'] + 1
item = origin.mixie_moodboard_images[-1]
assert item.image.packed_file and item.image.size[:] == (320, 240)
assert origin.render.image_settings.file_format == 'JPEG'
drv.main_window().scene = origin
with bpy.context.temp_override(window=drv.main_window()):
    receipt = jobs.start(bpy.context, '11111111111111111111111111111111')
assert receipt['status'] == 'done'
assert not slot.busy()
result = receipt
''')
    qa.step('image_visible', qa.snap, str(output / 'image-moodboard.png'))
    qa.step('video_start_receipt', qa.eval, start_code('2' * 32, 'video', 'QA Scene Video'))
    qa.step('video_completes', qa.wait,
            "bpy.app.driver_namespace.get('mixar_scene_render_results', {}).get('" + '2' * 32 + "', {}).get('status') != 'started'",
            timeout=60)
    video = qa.step('video_playable_and_settings_restored', qa.eval, '''
import os
scene = drv.main_window().scene
receipt = bpy.app.driver_namespace['mixar_scene_render_results']['22222222222222222222222222222222']
assert receipt['status'] == 'done', receipt
item = scene.mixie_moodboard_images[-1]
assert item.image.source == 'MOVIE' and item.image.frame_duration == 6
assert os.path.isfile(bpy.path.abspath(item.image.filepath))
assert 'generated_videos' in item.image.filepath
assert scene.render.image_settings.media_type == 'IMAGE'
assert scene.render.image_settings.file_format == 'JPEG'
assert scene.frame_current == bpy.app.driver_namespace['qa_render_frame']
result = {'receipt': receipt, 'video': bpy.path.abspath(item.image.filepath), 'frames': item.image.frame_duration}
''')
    qa.step('video_visible', qa.snap, str(output / 'video-moodboard.png'))
    qa.step('missing_camera_fails', qa.eval, '''
from mixar.modules.scene_render.core import jobs
with bpy.context.temp_override(window=drv.main_window()):
    scene = bpy.context.scene
    camera = scene.camera
    scene.camera = None
    receipt = jobs.start(bpy.context, '33333333333333333333333333333333')
    scene.camera = camera
assert receipt['error'] == 'camera_and_window_required'
result = receipt
''')
    qa.step('cancel_setup', qa.eval, '''
scene = drv.main_window().scene
scene.render.engine = 'CYCLES'
scene.cycles.samples = 512
scene.cycles.device = 'CPU'
scene.render.resolution_x = scene.render.resolution_y = 1024
result = True
''')
    qa.step('cancel_start', qa.eval, start_code('4' * 32, 'image', 'QA Cancelled'))
    qa.step('native_progress_visible', qa.snap, str(output / 'native-render-progress.png'))
    qa.step('native_stop', qa.click, text='Stop this job')
    qa.step('cancel_finishes', qa.wait,
            "bpy.app.driver_namespace.get('mixar_scene_render_results', {}).get('" + '4' * 32 + "', {}).get('status') != 'started'",
            timeout=60)
    qa.step('no_partial_item', qa.eval, '''
scene = drv.main_window().scene
receipt = bpy.app.driver_namespace['mixar_scene_render_results']['44444444444444444444444444444444']
assert receipt['status'] == 'cancelled', receipt
assert len(scene.mixie_moodboard_images) == bpy.app.driver_namespace['qa_render_count'] + 2
scene.render.engine = 'BLENDER_EEVEE'
scene.render.resolution_x, scene.render.resolution_y = 320, 240
result = receipt
''')
    project = str(output / 'render-delivery.blend')
    qa.step('save_with_other_scene_active', qa.eval, '''
origin = drv.main_window().scene
other = bpy.data.scenes['QA Other Scene']
other.collection.objects.link(origin.camera)
other.camera = origin.camera
drv.main_window().scene = other
result = other.name
''')
    qa.step('save_project', qa.eval, f"bpy.ops.wm.save_as_mainfile(filepath={project!r})\nresult=True")
    qa.step('reopen_project', qa.eval, f"bpy.ops.wm.open_mainfile(filepath={project!r})\nresult=True")
    qa.step('persistent_media_after_reopen', qa.eval, '''
import os
other = drv.main_window().scene
assert other.name == 'QA Other Scene'
scene = next(s for s in bpy.data.scenes if any(
    i.mixar_job_handle == '11111111111111111111111111111111' for i in s.mixie_moodboard_images))
images = [i.image for i in scene.mixie_moodboard_images if i.image]
still = next(i for i in images if i.name == 'QA Scene Image')
movie = next(i for i in images if i.name == 'QA Scene Video')
assert still.packed_file and still.size[:] == (320, 240)
assert movie.source == 'MOVIE' and movie.frame_duration == 6
assert os.path.isfile(bpy.path.abspath(movie.filepath))
from mixar.modules.scene_render.core import jobs
with bpy.context.temp_override(window=drv.main_window()):
    for expected in ('', scene.mixie_session_id):
        jobs._records.clear()  # Exercise persisted lookup for each replay shape.
        for key, kind in (('1' * 32, 'image'), ('2' * 32, 'video')):
            receipt = jobs.start(bpy.context, key, kind=kind, expected_session=expected)
            assert receipt['status'] == 'done' and receipt['scene_session'] == scene.mixie_session_id
assert not other.mixie_moodboard_images
assert jobs._job is None
assert not bpy.app.is_job_running('RENDER')
drv.main_window().scene = scene
result = {'packed': bool(still.packed_file), 'movie_frames': movie.frame_duration, 'replay_after_load': True}
''')
    qa.step('reopened_visible', qa.snap, str(output / 'reopened-moodboard.png'))
    if os.environ.get('QA_RENDER_AGENT') == '1':
        for kind in ('image', 'video'):
            count = qa.eval('result=len(drv.main_window().scene.mixie_moodboard_images)')
            qa.step('agent_asks_' + kind, qa.cmd, 'chat_send', text=(
                f'Render an {kind} of this scene using the current camera and settings. '
                'For video use the existing frames 1 to 6. Do not change the scene.'))
            turn = qa.step('agent_turn_' + kind, qa.cmd, 'wait_turn', timeout=180)
            reply = str(turn).lower()
            assert 'moodboard' in reply and ('start' in reply or 'rendering' in reply), turn
            qa.step('agent_delivers_' + kind, qa.wait,
                    f'len(drv.main_window().scene.mixie_moodboard_images) == {count + 1}', timeout=60)
            qa.step('agent_visible_' + kind, qa.snap, str(output / f'agent-{kind}.png'))
    return {'image': image, 'video': video, 'output': str(output)}


if __name__ == '__main__':
    run_scenario('scene_render_delivery', run)
