# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""No-credit GUI replay: project reloads, undo/redo and stale artifact fencing.

Run through $QA_HARNESS/run_scenarios.sh against an isolated Dev app.
Only temporary projects, artifacts and journals are used; no agent jobs run.
"""

import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import run_scenario


IMPORTS = '''
from mixar.modules.common.agent_execution import bindings, commit, document
fixture = drv._document_epoch_fixture
'''

SETUP = '''
import os
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from mixar.modules.common.agent_execution import artifacts, bindings, document, paths
from mixar.modules.common.agent_execution.journal import Journal
assert os.environ.get('MIXAR_QA') == '1'
assert not bindings._by_run, 'Use a fresh isolated app without real agent turns'
assert document._registered, 'Bootstrap must register the document callbacks'
scratch = tempfile.TemporaryDirectory(prefix='mixar-document-epoch-')
fixture = SimpleNamespace(scratch=scratch, old_cache=os.environ.get('MIXAR_AGENT_CACHE_DIR'))
drv._document_epoch_fixture = fixture
os.environ['MIXAR_AGENT_CACHE_DIR'] = scratch.name
fixture.journal = Journal(str(Path(scratch.name) / 'journal.sqlite'))
fixture.handlers = (('load_post', document._on_load_post),
                    ('undo_post', document._on_undo_post),
                    ('redo_post', document._on_redo_post))
for name, fn in fixture.handlers:
    assert getattr(bpy.app.handlers, name).count(fn) == 1
    assert hasattr(fn, '_bpy_persistent'), name
fixture.instance_id = bpy.context.window_manager.mixie_instance_id
artifact_id = str(uuid.uuid4())
artifact_path = str(Path(paths.staging_dir(fixture.instance_id)) / (artifact_id + '.blend'))
collection = bpy.data.collections['Collection']
bpy.data.libraries.write(artifact_path, {collection})
fixture.artifact = dict(artifact_id=artifact_id,
                        content_hash=artifacts.sha256_file(artifact_path),
                        collection_name=collection.name)
document.document_identity()  # Save stable document/scene IDs into the fixture.
fixture.project = str(Path(scratch.name) / 'project.mixar')
fixture.original_names = sorted(o.name for o in bpy.context.scene.objects)
with bpy.context.temp_override(window=drv.main_window()):
    assert bpy.ops.wm.save_as_mainfile(filepath=fixture.project) == {'FINISHED'}
result = True
'''

ACTIVATE = IMPORTS + '''
fixture.activation = dict(run_id='qa-document-' + str(TURN),
                          session_id='qa-document-session', turn_epoch=TURN)
accepted = bindings.activate(fixture.activation, journal=fixture.journal)
assert accepted['success'], accepted
fixture.epoch = accepted['document_epoch']
fixture.document_id = accepted['document_id']
assert bindings.bind_task(dict(run_id=fixture.activation['run_id'], turn_epoch=TURN,
                               task_id='qa-task', fence_token=1),
                          journal=fixture.journal)['success']
fixture.params = dict(fixture.artifact, run_id=fixture.activation['run_id'],
                      turn_epoch=TURN, task_id='qa-task', fence_token=1,
                      operation_id='qa-document-op-' + str(TURN), payload_hash='qa-payload')
result = True
'''

RELOAD = IMPORTS + '''
with bpy.context.temp_override(window=drv.main_window()):
    assert bpy.ops.wm.open_mainfile(filepath=fixture.project) == {'FINISHED'}
result = True
'''

CHECK_STALE = IMPORTS + '''
identity = document.document_identity()
assert identity['document_epoch'] > fixture.epoch
assert identity['document_id'] == fixture.document_id
for name, fn in fixture.handlers:
    assert getattr(bpy.app.handlers, name).count(fn) == 1, name
    assert hasattr(fn, '_bpy_persistent'), name
# WindowManager state is recreated on load; use the fixture's real staging root.
bpy.context.window_manager.mixie_instance_id = fixture.instance_id
before_names = sorted(o.name for o in bpy.context.scene.objects)
retry = bindings.activate(fixture.activation, journal=fixture.journal)
publish = commit.append_collection(fixture.params, journal=fixture.journal)
assert not retry['success'] and retry['error_type'] == 'stale_epoch', retry
assert not publish['success'] and publish['error_type'] == 'stale_epoch', publish
assert fixture.journal.op_get(fixture.params['operation_id']) is None
assert sorted(o.name for o in bpy.context.scene.objects) == before_names
result = dict(epoch=identity['document_epoch'], activation=retry['error_type'],
              commit=publish['error_type'], objects=before_names)
'''

ADD_UNDO_STEP = IMPORTS + '''
w = drv.main_window()
a = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
r = next(r for r in a.regions if r.type == 'WINDOW')
with bpy.context.temp_override(window=w, area=a, region=r):
    bpy.ops.ed.undo_push(message='QA document epoch baseline')
    bpy.ops.mesh.primitive_cube_add('EXEC_DEFAULT', False, location=(-4, 0, 0))
    bpy.context.object.name = 'QA_Epoch_Undo'
    bpy.ops.ed.undo_push(message='QA document epoch edit')
result = True
'''

UNDO_REDO = IMPORTS + '''
w = drv.main_window()
a = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
r = next(r for r in a.regions if r.type == 'WINDOW')
before = document.document_epoch()
with bpy.context.temp_override(window=w, area=a, region=r):
    assert getattr(bpy.ops.ed, ACTION)() == {'FINISHED'}
assert document.document_epoch() == before + 1
assert (bpy.data.objects.get('QA_Epoch_Undo') is not None) == (ACTION == 'redo')
result = True
'''

REPAIR = IMPORTS + '''
epoch = document.document_epoch()
bpy.app.handlers.undo_post.remove(document._on_undo_post)
assert document._registered
document.register()
document.register()
for name, fn in fixture.handlers:
    assert getattr(bpy.app.handlers, name).count(fn) == 1
assert document.document_epoch() == epoch
result = True
'''

PUBLISH_FRESH = IMPORTS + '''
fixture.params['placement'] = {'location': [4, 0, 0]}
published = commit.append_collection(fixture.params, journal=fixture.journal)
assert published['success'] and published['state'] == 'applied', published
assert len(published['receipt']['created_object_names']) == len(fixture.original_names)
w = drv.main_window()
a = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
r = next(r for r in a.regions if r.type == 'WINDOW')
with bpy.context.temp_override(window=w, area=a, region=r):
    for obj in bpy.context.scene.objects:
        obj.select_set(obj.type == 'MESH')
    smooth_view = bpy.context.preferences.view.smooth_view
    try:
        bpy.context.preferences.view.smooth_view = 0
        bpy.ops.view3d.view_selected(use_all_regions=False)
    finally:
        bpy.context.preferences.view.smooth_view = smooth_view
result = published
'''

CLEANUP = '''
import os
from mixar.modules.common.agent_execution import bindings, document
fixture = getattr(drv, '_document_epoch_fixture', None)
if fixture:
    bindings.reset()
    document.set_run_active(False)
    document.clear_foreground_tasks()
    if hasattr(fixture, 'project'):
        with bpy.context.temp_override(window=drv.main_window()):
            bpy.ops.wm.open_mainfile(filepath=fixture.project)
    if hasattr(fixture, 'journal'):
        fixture.journal.close()
    if fixture.old_cache is None:
        os.environ.pop('MIXAR_AGENT_CACHE_DIR', None)
    else:
        os.environ['MIXAR_AGENT_CACHE_DIR'] = fixture.old_cache
    fixture.scratch.cleanup()
    del drv._document_epoch_fixture
result = True
'''


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT') or tempfile.mkdtemp(prefix='mixar-epoch-qa-'))
    out.mkdir(parents=True, exist_ok=True)
    qa.cmd('wait_login', timeout=90)
    qa.wait("hasattr(bpy.context.window_manager, 'mixie_instance_id')", timeout=30)
    checks = []
    try:
        qa.step('save isolated project and real artifact', qa.eval, SETUP)
        for turn in (1, 2):
            qa.step(f'activate before reload {turn}', qa.eval, ACTIVATE.replace('TURN', str(turn)))
            qa.step(f'reload saved project {turn}', qa.eval, RELOAD)
            qa.wait('sorted(o.name for o in bpy.context.scene.objects) == '
                    'drv._document_epoch_fixture.original_names', timeout=15)
            checks.append(qa.step(f'reload {turn} refuses the old run', qa.eval, CHECK_STALE))
        snapshot(qa, out / 'epoch-after-reload.png')
        qa.step('repair a missing callback without duplication', qa.eval, REPAIR)
        qa.step('activate before undo', qa.eval, ACTIVATE.replace('TURN', '3'))
        qa.step('make a native undo step', qa.eval, ADD_UNDO_STEP)
        for action in ('undo', 'redo'):
            qa.step(f'native {action} after project reloads', qa.eval,
                    UNDO_REDO.replace('ACTION', repr(action)))
            checks.append(qa.step(f'{action} refuses the old run', qa.eval, CHECK_STALE))
            snapshot(qa, out / f'epoch-after-{action}.png')
        qa.step('activate a fresh run at the live epoch', qa.eval, ACTIVATE.replace('TURN', '4'))
        published = qa.step('fresh run publishes the real artifact', qa.eval, PUBLISH_FRESH)
        snapshot(qa, out / 'epoch-fresh-publish.png')
        return dict(credits_spent=0, fences=checks, fresh_publish=published,
                    snapshots=[str(p) for p in sorted(out.glob('epoch-*.png'))])
    finally:
        qa.eval(CLEANUP)


def snapshot(qa, path):
    # File load/undo replace region buffers. A state assertion can finish
    # before the viewport paints; request one frame and allow its event-loop
    # redraw to finish before the harness reads the cached window pixels.
    qa.eval("import time\n"
            "for area in drv.main_window().screen.areas: area.tag_redraw()\n"
            "drv._epoch_capture_after = time.monotonic() + 0.5")
    qa.wait("__import__('time').monotonic() >= drv._epoch_capture_after", timeout=5)
    qa.cmd('snap', path=str(path), area='VIEW_3D')


if __name__ == '__main__':
    run_scenario('document_epoch_lifecycle', run)
