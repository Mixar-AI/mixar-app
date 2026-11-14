#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Free native splat GUI replay in an isolated QA app, with no backend calls.

Requires QA_HARNESS, QA_SCENARIO_OUT, MIXAR_QA_PORT and optionally QA_CLIENT_ROOT.
QA_SPLAT_PREVIEW_DEVICE optionally selects CPU/GPU/AUTO for the preview only,
restoring the original scene preference; unset uses production defaults.
Reuses headless fixture writers. Drive File > Import, the real file browser,
viewport selection/hide/delete/undo, and File > Open legacy-file migration.
Read all emitted PNGs; state success alone does not establish visual quality.
The replay replaces the disposable QA scene and leaves the migrated world open.
"""
import json
import os
from pathlib import Path
import sys

harness = Path(os.environ['QA_HARNESS'])
sys.path[:0] = [str(harness), str(harness / 'scenarios')]
from lib import run_scenario
from export_formats_e2e import picker
from release_suite.native import capture, choose_file, file_browser, viewport_keyboard

FIXTURE_MODULE = '_qa_native_splat_fixtures'
READ = """
from mixar.modules.moodboard.core.splat_native import is_splat
w=drv.main_window()
result={'splats':[{'name':o.name,'type':o.type,'data_type':o.data.type,
                  'points':len(o.data.points),'hidden':o.hide_get(),
                  'selected':o.select_get(),'role':o.get('wl_role'),
                  'collections':[c.name for c in o.users_collection],
                  'matrix':[list(row) for row in o.matrix_world],
                  'attributes':sorted(a.name for a in o.data.attributes)}
                 for o in w.scene.objects if is_splat(o)],
        'objects':sorted(o.name for o in w.scene.objects),
        'lock_interface':w.scene.render.use_lock_interface,
        'active':w.view_layer.objects.active.name if w.view_layer.objects.active else None}
"""


def frame(qa):
    # A controlled view makes visible/hidden images directly comparable.
    qa.eval("""
from mathutils import Quaternion
w=drv.main_window()
a=next(a for a in w.screen.areas if a.type=='VIEW_3D')
a.spaces.active.shading.type='MATERIAL'
a.spaces.active.region_3d.view_rotation=Quaternion((0.7071068,0.7071068,0,0))
a.spaces.active.region_3d.view_location=(0,0,0.5)
a.spaces.active.region_3d.view_distance=6
a.tag_redraw()
result=True
""")


def state(qa, out, label):
    value = qa.eval(READ)
    (out / (label + '.json')).write_text(json.dumps(value, indent=2))
    capture(qa, out, label)
    return value


def import_file(qa, out, path, expected):
    picker(qa, 'Import', 'MIXIE_OT_import_splat')
    choose_file(qa, path)
    qa.wait("not any(a.type=='FILE_BROWSER' for w in bpy.context.window_manager.windows for a in w.screen.areas)", timeout=20)
    qa.wait("any(o.type=='POINTCLOUD' for o in drv.main_window().scene.objects)", timeout=10)
    frame(qa)
    value = state(qa, out, path.stem + '-imported')
    assert len(value['splats']) == expected, value
    newest = next(s for s in value['splats'] if s['name'] == value['active'])
    assert newest['points'] == 400 and newest['role'] == 'splat', newest
    assert newest['data_type'] == 'GAUSSIAN_SPLAT' and newest['selected'], newest
    assert not newest['hidden'], newest
    return value


def _inspection_preview(qa, out, key):
    """Exercise the same local entry point used by engine=splat agent captures."""
    module = "__import__('mixar.modules.space_mixie_chat.core.preview_render',fromlist=['poll'])"
    baseline = qa.eval(READ)
    settings = "result={'engine':drv.main_window().scene.render.engine,'camera':str(drv.main_window().scene.camera),'world':str(drv.main_window().scene.world),'objects':len(bpy.data.objects),'scenes':len(bpy.data.scenes)}"
    before = qa.eval(settings)
    started = qa.eval(f"""
from mixar.modules.space_mixie_chat.core import preview_render
with bpy.context.temp_override(window=drv.main_window()):
    result=preview_render.start(bpy.context,{key!r},inspection={{'engine':'splat','view':'hero','shading':'solid','width':320,'height':240}})
""")
    assert started['status'] in ('running', 'done'), started
    qa.wait(f"{module}.poll({key!r})['status'] not in ('running','queued')", timeout=90)
    value = qa.eval(f"""
import base64
from pathlib import Path
from mixar.modules.space_mixie_chat.core import preview_render
value=dict(preview_render.poll({key!r}))
assert value['status']=='done',value
encoded=value.pop('image_base64')
Path({str(out / 'inspection-engine-splat.png')!r}).write_bytes(base64.b64decode(encoded))
result=value
""")
    assert value['success'] and value['engine'] == 'CYCLES', value
    assert value['width'] == 320 and value['height'] == 240, value
    assert qa.eval(READ) == baseline, 'inspection mutated the source world'
    assert qa.eval(settings) == before, 'inspection left private scene/rig or changed source settings'
    value['source_unchanged'] = True
    (out / 'inspection-engine-splat.json').write_text(json.dumps(value, indent=2))
    return value


def inspection_preview(qa, out):
    import uuid
    key = uuid.uuid4().hex
    device = os.environ.get('QA_SPLAT_PREVIEW_DEVICE', '').upper()
    assert device in ('', 'CPU', 'GPU', 'AUTO'), device
    original = qa.eval("result=drv.main_window().scene.mixar_paint_preferences.default_render_device")
    scope = {'request_device': device or 'production-default', 'original_preference': original,
             'key': key, 'automatic_fallback': False}
    try:
        if device:
            qa.eval(f"drv.main_window().scene.mixar_paint_preferences.default_render_device={device!r}\nresult=True")
        result = _inspection_preview(qa, out, key)
        scope['effective_device'] = result['render']['device']
        if device == 'CPU':
            assert scope['effective_device'] == 'CPU', scope
        result['device_scope'] = scope
        return result
    finally:
        # Cancel only a worker belonging to this exact replay request. A failed
        # bounded wait must not leave a process rendering after the case ends.
        scope['cleanup'] = qa.eval(f"""
from mixar.modules.space_mixie_chat.core import preview_render as p
from mixar.modules.common.render_worker import supervisor
job=p._job
cleanup={{'cancelled_worker':None,'native_pending':False}}
if job is not None and job['key']=={key!r}:
    if job.get('worker'):
        cleanup['cancelled_worker']=job['worker']
        cleanup['state_before_cancel']=supervisor.poll(job['worker'])
        supervisor.cancel(job['worker'])
        p.poll({key!r})
    else:
        cleanup['native_pending']=True
result=cleanup
""")
        if scope['cleanup']['native_pending']:
            # The guarded native fallback is the only remaining render, so its
            # ordinary Escape action cannot cancel another controller's job.
            qa.press('ESC', window=viewport_keyboard(qa))
            qa.wait("not bpy.app.is_job_running('RENDER')", timeout=10)
        qa.eval(f"drv.main_window().scene.mixar_paint_preferences.default_render_device={original!r}\nresult=True")
        scope['preference_restored'] = qa.eval("result=drv.main_window().scene.mixar_paint_preferences.default_render_device") == original
        (out / 'inspection-device-scope.json').write_text(json.dumps(scope, indent=2))
        assert scope['preference_restored'], scope


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT']).resolve()
    out.mkdir(parents=True, exist_ok=True)
    client = Path(os.environ.get('QA_CLIENT_ROOT', Path(__file__).resolve().parents[2]))
    fixture = client / 'tests/qa/native_splats_background.py'
    qa.dismiss_splash()
    qa.cmd('dismiss_chat')
    identity = qa.eval("import os,sys\nassert os.environ.get('MIXAR_QA')=='1'\n"
                       "assert bpy.app.version[:2]==(5,3)\n"
                       "result={'version':bpy.app.version_string,'platform':sys.platform,'binary':bpy.app.binary_path}")
    paths = {ext: out / ('native-' + ext + '.' + ext) for ext in ('ply', 'spz')}
    legacy = out / 'legacy-kiri.mixar'
    # Fixture creation is the only direct scene construction. Import, editing
    # and migration below use normal UI operators and production handlers.
    qa.eval(f"""
import importlib.util,sys
spec=importlib.util.spec_from_file_location({FIXTURE_MODULE!r},{str(fixture)!r})
f=importlib.util.module_from_spec(spec)
sys.modules[{FIXTURE_MODULE!r}]=f
spec.loader.exec_module(f)
w=drv.main_window()
for o in list(w.scene.objects): bpy.data.objects.remove(o,do_unlink=True)
positions=f.np.random.default_rng(7).uniform(-1,1,(400,3))
f.raw_ply({str(paths['ply'])!r},positions)
f.pathlib.Path({str(paths['spz'])!r}).write_bytes(f.spz_bytes(positions))
with bpy.context.temp_override(window=w): bpy.ops.ed.undo_push(message='QA splat fixture')
result=True
""")
    result = {'identity': identity, 'backend_calls': 0, 'stages': {}}
    try:
        result['stages']['ply'] = qa.step('ply-file-menu-import', import_file, qa, out, paths['ply'], 1)
        name = result['stages']['ply']['active']
        window = viewport_keyboard(qa)
        qa.press('H', window=window)
        qa.wait(f'bpy.data.objects[{name!r}].hide_get()', timeout=5)
        result['stages']['hidden'] = state(qa, out, 'ply-hidden')
        qa.press('H', alt=True, window=window)
        qa.wait(f'not bpy.data.objects[{name!r}].hide_get()', timeout=5)
        qa.press('A', alt=True, window=window)
        qa.wait(f'not bpy.data.objects[{name!r}].select_get()', timeout=5)
        qa.press('A', window=window)
        qa.wait(f'bpy.data.objects[{name!r}].select_get()', timeout=5)
        result['stages']['selected'] = state(qa, out, 'ply-selected')
        qa.press('X', window=window)
        qa.wait("bool(drv.find(popup=True,text='Delete',but_type='But'))", timeout=5)
        qa.click(popup=True, text='Delete', but_type='But')
        qa.wait(f'{name!r} not in bpy.data.objects', timeout=8)
        result['stages']['deleted'] = state(qa, out, 'ply-deleted')
        assert not result['stages']['deleted']['splats']
        window = viewport_keyboard(qa)
        qa.press('Z', ctrl=True, window=window)
        qa.wait(f'{name!r} in bpy.data.objects', timeout=8)
        restored = state(qa, out, 'ply-undo-restored')
        assert len(restored['splats']) == 1 and restored['splats'][0]['points'] == 400, restored
        result['stages']['undo'] = restored
        result['stages']['spz'] = qa.step('spz-file-menu-import', import_file, qa, out, paths['spz'], 2)
        matrix = qa.eval(f"""
import sys
f=sys.modules[{FIXTURE_MODULE!r}]
w=drv.main_window()
for o in list(w.scene.objects): bpy.data.objects.remove(o,do_unlink=True)
with bpy.context.temp_override(window=w):
    matrix=f.kiri_world()
    bpy.ops.wm.save_as_mainfile(filepath={str(legacy)!r})
result=[list(row) for row in matrix]
""")
        assert legacy.is_file() and legacy.stat().st_size > 1024
        (out / 'legacy-expected-matrix.json').write_text(json.dumps(matrix, indent=2))
        file_browser(qa, 'WM_OT_open_mainfile')
        choose_file(qa, legacy)
        qa.wait("bpy.data.objects.get('Old_Splat') is not None and bpy.data.objects['Old_Splat'].type=='POINTCLOUD'", timeout=20)
        frame(qa)
        migrated = state(qa, out, 'legacy-file-migrated')
        assert len(migrated['splats']) == 1, migrated
        splat = migrated['splats'][0]
        assert splat['name'] == 'Old_Splat' and splat['points'] == 400 and not splat['hidden'], splat
        assert {'radiance:base', 'radiance:sh_0', 'radiance:sh_2'} <= set(splat['attributes']), splat
        assert all(abs(a-b) < 1e-4 for ra,rb in zip(matrix,splat['matrix']) for a,b in zip(ra,rb)), (matrix, splat['matrix'])
        assert 'Old_SplatSource' not in migrated['objects'] and 'Old_SplatProxy' not in migrated['objects']
        assert 'Old_Collider' in migrated['objects'] and not migrated['lock_interface'], migrated
        assert qa.eval("result=bpy.data.node_groups.get('KIRI_3DGS_Render_GN') is None")
        result['stages']['legacy_file'] = migrated
        result['stages']['inspection_preview'] = qa.step('native-engine-splat-preview', inspection_preview, qa, out)
        result['completed'] = True
        return result
    finally:
        (out / 'native-splats-gui.json').write_text(json.dumps(result, indent=2))
        qa.eval(f"import sys\nsys.modules.pop({FIXTURE_MODULE!r},None)\nresult=True")


if __name__ == '__main__':
    run_scenario('native_splats_gui_e2e', run)
