#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""No-credit real Cycles/GLB/archive collision regression in an isolated QA app.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4798 \
QA_SCENARIO_OUT=/tmp/render-qa python3 tests/qa/render_archive_coordination_e2e.py

Uses a locally exported GLB through ModelIO and AsyncGLBJob.on_imported;
only library destination/retraining are redirected. Both renders and .blend
export are real. Delays agent finalization deliberately to exercise the gap
between native job teardown and copying Render Result. Inspect evidence PNGs.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

IMPORTS = '''
import base64, json, os, uuid
from pathlib import Path
from types import SimpleNamespace
from mixar.modules.common.render_coordinator import core as slot
from mixar.modules.asset_search.core import generation_library as gl
from mixar.modules.space_mixie_chat.core import preview_render as preview
from mixar.modules.common.job_queue.core.generic_jobs import AsyncGLBJob
from mixar.modules.common.job_queue.core.job import JobState
from mixar.modules.common.job_queue.core.model_io import import_file
'''

SETUP = IMPORTS + '''
assert os.environ.get('MIXAR_QA') == '1', 'Use an isolated QA profile'
assert not slot.busy()
root = Path(os.environ['MIXAR_QA_OUT']) / ('render-coordination-' + uuid.uuid4().hex[:8])
root.mkdir(exist_ok=True)
f = drv._render_qa = SimpleNamespace(root=root, allow_finish=False, imported=False,
    import_error=None, deferred=0, finalizing_seen=False, original_finish=preview._finish,
    original_tick=gl._process_archive_queue, original_path=gl.get_library_path,
    original_retrain=gl._schedule_retrain, original_save=gl._save_job, saves=[])
# Archive output is a disposable QA library; no embedding/backend job is sent.
gl.get_library_path = lambda: str(root / 'library')
(root / 'library').mkdir(exist_ok=True)
(root / 'recon-library').mkdir(exist_ok=True)
gl._schedule_retrain = lambda: None
def save(job):
    f.saves.append(job.id)
    return f.original_save(job)
gl._save_job = save

def tick():
    if slot.busy():
        f.deferred += 1
    return f.original_tick()
gl._process_archive_queue = tick

def finish(key, completed, lost=False):
    if not bpy.app.is_job_running('RENDER') and not f.allow_finish:
        f.finalizing_seen = True
        return 0.1
    return f.original_finish(key, completed, lost)
preview._finish = finish

with bpy.context.temp_override(window=drv.main_window()):
    scene = bpy.context.scene
    f.scene = scene
    # Local fixture with a red material, exported then removed before rendering.
    bpy.ops.object.select_all(action='DESELECT')
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, location=(3, 0, 1))
    obj = bpy.context.object
    obj.name = 'QA_Generated_Red_Sphere'
    mat = bpy.data.materials.new('QA_Red')
    mat.use_nodes = True
    mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value = (0.8, 0.02, 0.02, 1)
    obj.data.materials.append(mat)
    f.glb = str(root / 'fixture.glb')
    bpy.ops.export_scene.gltf(filepath=f.glb, export_format='GLB', use_selection=True)
    bpy.data.objects.remove(obj, do_unlink=True)
    if scene.camera is None:
        bpy.ops.object.camera_add(location=(7, -7, 5))
        scene.camera = bpy.context.object
        from mathutils import Vector
        scene.camera.rotation_euler = (Vector((0, 0, 0)) - scene.camera.location).to_track_quat('-Z', 'Y').to_euler()
    scene.render.engine = 'CYCLES'
    scene.render.resolution_x = 640
    scene.render.resolution_y = 480
    scene.render.resolution_percentage = 100
    f.before = (scene.render.engine, scene.camera.name, scene.render.resolution_x,
                scene.render.resolution_y, {o.name: o.hide_render for o in scene.objects})
result = str(root)
'''

START = IMPORTS + '''
f = drv._render_qa
with bpy.context.temp_override(window=drv.main_window()):
    value = preview.start(bpy.context, 'a' * 32, width=1024, height=768, engine='cycles')
assert value['status'] == 'running', value['status']
f.render_info = value['render']

def land_model():
    try:
        assert bpy.app.is_job_running('RENDER'), 'Render must overlap fixture import'
        with bpy.context.temp_override(window=drv.main_window()):
            names = import_file(f.glb, 'GLB')
            job = AsyncGLBJob(label='QA generated sphere', job_type='model_3d')
            job.on_imported(names)
            job.state = JobState.SUCCESS
            f.job = job
            gl._on_queue_changed(SimpleNamespace(snapshot=lambda: [job]))
            from mixar.modules.moodboard.core.scene_asset_exporter import schedule_object_export
            schedule_object_export(gl._pick_mesh(names), 'QA reconstruction', str(f.root / 'recon-library'))
        assert gl._archive_queue and not f.saves
        f.imported = True
    except Exception as exc:
        f.import_error = str(exc)
    return None
bpy.app.timers.register(land_model, first_interval=0.0)
result = value
'''

FINALIZING = IMPORTS + '''
f = drv._render_qa
assert f.imported and not f.import_error, f.import_error
assert f.finalizing_seen and not bpy.app.is_job_running('RENDER')
assert slot.busy() and gl._archive_queue
assert not f.saves and not list((f.root / 'library').rglob('*.blend'))
assert not list((f.root / 'recon-library').rglob('*.blend'))
assert f.deferred > 0
f.allow_finish = True
result = {'deferred_ticks': f.deferred, 'render': f.render_info}
'''

VERIFY = IMPORTS + '''
f = drv._render_qa
value = preview.poll('a' * 32)
assert value['status'] == 'done', value['status']
assert len(f.saves) == 1 and not gl._archive_queue and not slot.busy()
files = list((f.root / 'library').rglob('*.blend'))
assert len(files) == 1, files
recon_files = list((f.root / 'recon-library').rglob('*.blend'))
assert len(recon_files) == 1, recon_files
scene = f.scene
assert (scene.render.engine, scene.camera.name, scene.render.resolution_x,
        scene.render.resolution_y) == f.before[:4]
assert all(scene.objects[name].hide_render == hidden for name, hidden in f.before[4].items())
assert not any(o.name.startswith(('_asset_preview_cam', '_asset_preview_key', '_asset_preview_fill')) for o in scene.objects)
agent_path = f.root / 'agent-render.png'
agent_path.write_bytes(base64.b64decode(value['image_url'].split(',', 1)[1]))
with bpy.data.libraries.load(str(files[0]), link=True) as (source, dest):
    dest.objects = list(source.objects)
asset = next(o for o in dest.objects if o.type == 'MESH')
p = asset.preview
assert p and min(p.image_size) >= 32
img = bpy.data.images.new('QA archived thumbnail', width=p.image_size[0], height=p.image_size[1], alpha=True)
img.pixels.foreach_set(list(p.image_pixels_float))
img.filepath_raw = str(f.root / 'asset-thumbnail.png')
img.file_format = 'PNG'
img.save()
bpy.data.images.remove(img)
bpy.data.libraries.remove(asset.library)
result = {'agent_image': str(agent_path), 'asset_thumbnail': str(f.root / 'asset-thumbnail.png'),
          'archive': str(files[0]), 'reconstruction_archive': str(recon_files[0]),
          'deferred_ticks': f.deferred, 'saves': len(f.saves)}
'''

NATIVE = IMPORTS + '''
f = drv._render_qa
assert not slot.busy()
with bpy.context.temp_override(window=drv.main_window()):
    view = bpy.context.preferences.view
    old = view.render_display_type
    try:
        view.render_display_type = 'NONE'
        assert bpy.ops.render.render('INVOKE_DEFAULT') == {'RUNNING_MODAL'}
    finally:
        view.render_display_type = old
    assert bpy.app.is_job_running('RENDER') and slot._active is None
    jobs = [AsyncGLBJob(label='QA native ' + str(i), job_type='model_3d') for i in range(2)]
    for job in jobs:
        job.imported_object_names = f.job.imported_object_names
        job.state = JobState.SUCCESS
    gl._on_queue_changed(SimpleNamespace(snapshot=lambda: jobs))
    assert gl._process_archive_queue() == 0.25
    assert len(gl._archive_queue) == 2 and len(f.saves) == 1
result = True
'''

CANCEL = IMPORTS + '''
f = drv._render_qa
assert len(f.saves) == 3 and len(set(f.saves)) == 3
assert not slot.busy()
with bpy.context.temp_override(window=drv.main_window()):
    value = preview.start(bpy.context, 'b' * 32, width=1920, height=1440, engine='cycles')
assert value['status'] == 'running'
result = value
'''

DIRECTOR = IMPORTS + '''
from mixar.modules.director.core import render_outputs as director
f = drv._render_qa
f.director_gap = False
f.original_next_pass = director._queue_next_pass
f.movies_before = {i.name for i in bpy.data.images if i.source == 'MOVIE'}
def next_pass(target):
    assert slot.owns(director._job['reservation'])
    assert gl._process_archive_queue() == 0.25
    f.director_gap = True
    return f.original_next_pass(target)
director._queue_next_pass = next_pass
with bpy.context.temp_override(window=drv.main_window()):
    scene = bpy.context.scene
    scene.render.resolution_x = scene.render.resolution_y = 256
    camera = scene.camera
    camera.keyframe_insert(data_path='location', frame=1)
    camera.keyframe_insert(data_path='location', frame=2)
    settings = scene.mixar_camera_export
    settings.render_output_types = {'CLAY', 'DEPTH'}
    settings.render_resolution_percentage = 100
    from mixar.modules.space_mixie_chat.core.executor import ScriptExecutor
    execution = ScriptExecutor().execute(
        "bpy.ops.mixar.render_camera_to_moodboard()", push_undo=False)
    assert execution.success, execution.error
    assert director._on_render_complete in bpy.app.handlers.render_complete
    assert director._on_render_cancel in bpy.app.handlers.render_cancel
    assert director._before_load in bpy.app.handlers.load_pre
    assert slot.owns(director._job['reservation'])
    job = AsyncGLBJob(label='QA director deferred', job_type='model_3d')
    job.imported_object_names = f.job.imported_object_names
    job.state = JobState.SUCCESS
    gl._on_queue_changed(SimpleNamespace(snapshot=lambda: [job]))
    assert len(gl._archive_queue) == 1
result = True
'''

VERIFY_DIRECTOR = IMPORTS + '''
from mixar.modules.director.core import render_outputs as director
f = drv._render_qa
assert f.director_gap and director._job is None
assert len(f.saves) == 4 and len(set(f.saves)) == 4
assert not slot.busy()
settings = f.scene.mixar_camera_export
assert settings.render_status == 'Added 2 videos to Moodboard', settings.render_status
movies = [i.filepath for i in bpy.data.images if i.source == 'MOVIE' and i.name not in f.movies_before]
assert len(movies) == 2, movies
assert all(Path(p).is_file() for p in movies)
assert f.scene.render.engine == 'CYCLES'
result = {'movies': movies, 'status': settings.render_status}
'''

CLEANUP = IMPORTS + '''
f = drv._render_qa
if hasattr(f, 'original_next_pass'):
    from mixar.modules.director.core import render_outputs as director
    director._queue_next_pass = f.original_next_pass
preview._finish = f.original_finish
gl._process_archive_queue = f.original_tick
gl._save_job = f.original_save
gl.get_library_path = f.original_path
gl._schedule_retrain = f.original_retrain
result = True
'''


def run(qa):
    qa.step('login', qa.cmd, 'wait_login', timeout=60)
    qa.eval("import os\nassert os.environ.get('MIXAR_QA') == '1'\nresult = True")
    qa.step('clean_scene', qa.cmd, 'reset_state')
    qa.step('reconnect', qa.cmd, 'wait_login', timeout=60)
    qa.step('dismiss_splash', qa.cmd, 'dismiss_splash')
    qa.step('setup_local_glb', qa.eval, SETUP)
    try:
        qa.step('start_cycles_and_import', qa.eval, START)
        qa.step('wait_finalization_gap', qa.wait,
                "drv._render_qa.finalizing_seen or drv._render_qa.import_error is not None", timeout=120)
        qa.step('assert_archive_waited', qa.eval, FINALIZING)
        qa.step('wait_archive', qa.wait,
                "bool(drv._render_qa.saves) and bool(list((drv._render_qa.root / 'recon-library').rglob('*.blend'))) and not __import__('mixar.modules.common.render_coordinator.core', fromlist=['busy']).busy()", timeout=90)
        evidence = qa.step('verify_results_and_restore', qa.eval, VERIFY)
        qa.step('viewport_evidence', qa.snap, str(Path(evidence['agent_image']).with_name('viewport.png')))
        qa.step('native_render_two_archives', qa.eval, NATIVE)
        qa.step('wait_native_archives', qa.wait,
                "len(drv._render_qa.saves) == 3 and not __import__('mixar.modules.common.render_coordinator.core', fromlist=['busy']).busy()", timeout=90)
        qa.step('start_render_to_cancel', qa.eval, CANCEL)
        qa.step('stop_native_job', qa.click, text='Stop this job')
        qa.step('wait_cancel', qa.wait,
                "__import__('mixar.modules.space_mixie_chat.core.preview_render', fromlist=['poll']).poll('b' * 32)['status'] != 'running'", timeout=90)
        qa.step('assert_cancelled_and_released', qa.eval, IMPORTS +
                "assert preview.poll('b' * 32)['status'] == 'cancelled'\nassert not slot.busy()\nresult = True")
        qa.step('director_two_pass_export', qa.eval, DIRECTOR)
        qa.step('wait_director_archive', qa.wait,
                "len(drv._render_qa.saves) == 4 and not __import__('mixar.modules.common.render_coordinator.core', fromlist=['busy']).busy()", timeout=90)
        director = qa.step('verify_director_outputs', qa.eval, VERIFY_DIRECTOR)
        return dict(evidence, native_archives=2, cancellation='passed', director=director)
    finally:
        qa.eval(CLEANUP)


if __name__ == '__main__':
    run_scenario('render_archive_coordination', run)
