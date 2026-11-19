#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Free GUI replay of the local splat import's Source option (no backend calls).

Requires QA_HARNESS, QA_SCENARIO_OUT, MIXAR_QA_PORT and optionally QA_CLIENT_ROOT.
QA_SPLAT_SAMPLE optionally names a real spec SPZ (e.g. Niantic's
hornedlizard.spz) for the visual stage; it is skipped when the file is absent.

Drives File (or the narrow-bar logo menu > File) > Import > Gaussian Splat,
Grounded, the real file browser and its Source dropdown, like a person:
  * Standard (default): a spec-frame marker SPZ lands Z-up with no object
    rotation (file +Y up -> +Z, file -Z forward -> +Y);
  * World Labs: the same file takes the 180 deg X object rotation, so it lands
    where the retired converter path put Marble worlds;
  * a corrupt .spz is reported and leaves no object or Splat_* collection;
  * optional real sample: imported upright and framed for the vision check.
Read every emitted PNG; state success alone does not establish what it looks like.
"""
import json
import os
from pathlib import Path
import sys

harness = Path(os.environ['QA_HARNESS'])
sys.path[:0] = [str(harness), str(harness / 'scenarios')]
from lib import choose_in_dropdown, ensure_scenes_drawer, run_scenario
from release_suite.native import choose_file

FIXTURE_MODULE = '_qa_splat_source_fixtures'
SOURCE = {'area_type': 'FILE_BROWSER', 'prop': 'source'}
NO_BROWSER = ("not any(a.type=='FILE_BROWSER' for w in bpy.context.window_manager.windows "
              "for a in w.screen.areas)")
READ = """
import math
from mixar.modules.moodboard.core.splat_native import is_splat
w=drv.main_window()
def pts(o):
    import numpy as np
    from mathutils import Vector
    a=np.empty(len(o.data.points)*3,dtype=np.float32)
    o.data.attributes['position'].data.foreach_get('vector',a)
    return [tuple(round(c,2) for c in o.matrix_world@Vector(a[i:i+3])) for i in range(0,min(len(a),9),3)]
result={'splats':[{'name':o.name,'points':len(o.data.points),'first_points':pts(o),
                  'rotation_deg':[round(math.degrees(r)) for r in o.rotation_euler],
                  'role':o.get('wl_role'),'collections':[c.name for c in o.users_collection]}
                 for o in w.scene.objects if is_splat(o)],
        'objects':sorted(o.name for o in w.scene.objects),
        'splat_collections':sorted(c.name for c in bpy.data.collections if c.name.startswith('Splat_')),
        'active':w.view_layer.objects.active.name if w.view_layer.objects.active else None}
"""


def clear_scene(qa):
    qa.eval("""
w=drv.main_window()
for o in list(w.scene.objects): bpy.data.objects.remove(o,do_unlink=True)
for c in [c for c in bpy.data.collections if c.name.startswith('Splat_')]: bpy.data.collections.remove(c)
result=True
""")


def open_menu(qa, query, expect):
    """Click a top-bar menu and verify it opened (shows popup ``expect``).

    The first injected click on the main window after the separate file
    browser closes can be dropped on Windows (focus returns with it), so
    retry ONCE, and only while no popup is open.
    """
    for attempt in (1, 2):
        qa.click(**query)
        try:
            qa.wait(f"bool(drv.find(popup=True, text={expect!r}))", timeout=3)
            return attempt
        except Exception:  # noqa: BLE001 - one verified retry, see docstring
            if attempt == 2 or qa.find(popup=True)['total']:
                raise


def open_import(qa):
    """File (or the logo menu > File) > Import > Gaussian Splat, Grounded."""
    qa.cmd('dismiss_chat')
    # A wide top bar shows File itself; a narrow one folds the menus into the
    # unlabeled logo pulldown (the driver matches `text` on its tooltip).
    if qa.find(area_type='TOPBAR', but_type='Pulldown', text='File')['total']:
        open_menu(qa, dict(area_type='TOPBAR', but_type='Pulldown', text='File'), 'Import')
    else:
        open_menu(qa, dict(area_type='TOPBAR', but_type='Pulldown',
                           text='Mixar, File, Edit, Render, Window and Help menus'), 'File')
        qa.click(popup=True, text='File')
    qa.click(popup=True, text='Import')
    found = qa.find(popup=True, op='MIXIE_OT_import_splat')
    assert found['total'] == 1, found
    label = found['widgets'][0]['text']
    assert label == 'Gaussian Splat, Grounded (.spz/.ply)', label
    qa.click(popup=True, op='MIXIE_OT_import_splat')
    qa.wait("bool(drv.find(area_type='FILE_BROWSER',prop='filename'))", timeout=10)
    return label


def execute_picker(qa, path, timeout=20):
    """Pick ``path`` and press Import, verifying the press landed.

    On Windows the first injected click into the separate file-browser window
    after the filename edit can be dropped (the harness README's first-click
    rule): read state, click, verify, and retry ONCE only while the browser
    is still open on the same file and nothing was imported.
    """
    choose_file(qa, path, execute=False)
    before = qa.eval(READ)['objects']
    for attempt in (1, 2):
        qa.click(area_type='FILE_BROWSER', op='FILE_OT_execute')
        try:
            qa.wait(NO_BROWSER, timeout=timeout if attempt == 2 else 3)
            return attempt
        except Exception:  # noqa: BLE001 - checked below before the one retry
            still_open = qa.find(area_type='FILE_BROWSER', op='FILE_OT_execute')['total']
            if attempt == 2 or not still_open or qa.eval(READ)['objects'] != before:
                raise
    return 2


def source_text(qa):
    return qa.find(**SOURCE)['widgets'][0]['text']


def state(qa, out, label):
    value = qa.eval(READ)
    (out / (label + '.json')).write_text(json.dumps(value, indent=2))
    qa.cmd('snap', path=str(out / (label + '.png')), area='VIEW_3D')
    return value


def import_marker(qa, out, path, source, label):
    clear_scene(qa)
    open_import(qa)
    assert source_text(qa) == 'Standard', 'Source must default to Standard'
    if source != 'Standard':
        choose_in_dropdown(qa, SOURCE, source)
        qa.wait(f"drv.find(area_type='FILE_BROWSER',prop='source')[0]['text']=={source!r}", timeout=5)
    clicks = execute_picker(qa, path)
    qa.wait("any(o.type=='POINTCLOUD' for o in drv.main_window().scene.objects)", timeout=15)
    value = state(qa, out, label)
    assert len(value['splats']) == 1, value
    splat = value['splats'][0]
    splat['execute_clicks'] = clicks
    assert splat['role'] == 'splat' and splat['name'] == value['active'], splat
    assert splat['collections'][0].startswith('Splat_'), splat
    return splat


def corrupt_refused(qa, out, path):
    clear_scene(qa)
    before = qa.eval(READ)
    open_import(qa)
    execute_picker(qa, path)
    log = Path(qa.eval("import os\nresult=os.environ['MIXAR_QA_OUT']")) / 'app.log'
    qa.wait(f"{path.name!r} in open({str(log)!r},encoding='utf-8',errors='replace').read()", timeout=10)
    after = state(qa, out, 'corrupt-refused')
    assert after['objects'] == before['objects'], (before, after)
    assert after['splat_collections'] == before['splat_collections'], (before, after)
    lines = [l for l in log.read_text(encoding='utf-8', errors='replace').splitlines()
             if path.name in l and 'SplatImport' in l]
    assert lines, 'the failure was not reported'
    return {'reported': lines[-1][-200:]}


def frame_core(qa):
    """Look at the dense core from the front; the far sky shell would zoom out."""
    qa.eval("""
import numpy as np
from mathutils import Euler, Vector
w=drv.main_window()
o=w.view_layer.objects.active
a=np.empty(len(o.data.points)*3,dtype=np.float32)
o.data.attributes['position'].data.foreach_get('vector',a)
a=a.reshape(-1,3); m=np.array(o.matrix_world); a=a@m[:3,:3].T+m[:3,3]
lo,hi=np.percentile(a,25,axis=0),np.percentile(a,75,axis=0)
area=next(x for x in w.screen.areas if x.type=='VIEW_3D')
sp=area.spaces.active; sp.shading.type='MATERIAL'
r3=sp.region_3d; r3.view_perspective='PERSP'
r3.view_location=Vector(((lo+hi)/2).tolist())
r3.view_rotation=Euler((1.22,0,0)).to_quaternion()
r3.view_distance=float(np.linalg.norm(hi-lo))*1.4
area.tag_redraw()
result=True
""")


def real_sample(qa, out, path):
    clear_scene(qa)
    open_import(qa)
    execute_picker(qa, path, timeout=30)
    qa.wait("any(o.type=='POINTCLOUD' for o in drv.main_window().scene.objects)", timeout=30)
    frame_core(qa)
    value = state(qa, out, 'real-sample-standard')
    splat = value['splats'][0]
    assert splat['rotation_deg'] == [0, 0, 0] and splat['points'] > 100000, splat
    return splat


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT']).resolve()
    out.mkdir(parents=True, exist_ok=True)
    client = Path(os.environ.get('QA_CLIENT_ROOT', Path(__file__).resolve().parents[2]))
    fixture = client / 'tests/qa/native_splats_background.py'
    qa.dismiss_splash()
    ensure_scenes_drawer(qa)
    identity = qa.eval("import os,sys\nassert os.environ.get('MIXAR_QA')=='1'\n"
                       "result={'version':bpy.app.version_string,'platform':sys.platform,"
                       "'io_spz':bool(bpy.app.build_options.io_spz)}")
    assert identity['io_spz'], identity
    marker, corrupt = out / 'marker.spz', out / 'corrupt.spz'
    # Fixture writing is the only direct construction; every import is the UI.
    qa.eval(f"""
import importlib.util,sys
spec=importlib.util.spec_from_file_location({FIXTURE_MODULE!r},{str(fixture)!r})
f=importlib.util.module_from_spec(spec); sys.modules[{FIXTURE_MODULE!r}]=f
spec.loader.exec_module(f)
f.pathlib.Path({str(marker)!r}).write_bytes(f.spz_bytes([(0,1,0),(1,0,0),(0,0,-1)]))
f.pathlib.Path({str(corrupt)!r}).write_bytes(b'not a gzip spz file')
result=True
""")
    result = {'identity': identity, 'backend_calls': 0, 'stages': {}}
    try:
        std = qa.step('standard-source', import_marker, qa, out, marker, 'Standard', 'marker-standard')
        assert std['rotation_deg'] == [0, 0, 0], std
        assert std['first_points'] == [[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], std
        result['stages']['standard'] = std
        wl = qa.step('world-labs-source', import_marker, qa, out, marker, 'World Labs', 'marker-world-labs')
        assert wl['rotation_deg'] == [180, 0, 0], wl
        assert [tuple(abs(c) if c == 0 else c for c in p) for p in wl['first_points']] == \
            [(0.0, 0.0, -1.0), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0)], wl
        result['stages']['world_labs'] = wl
        result['stages']['corrupt'] = qa.step('corrupt-spz-refused', corrupt_refused, qa, out, corrupt)
        sample = Path(os.environ.get('QA_SPLAT_SAMPLE', 'D:/splats/hornedlizard.spz'))
        if sample.is_file():
            result['stages']['real_sample'] = qa.step('real-sample-upright', real_sample, qa, out, sample)
        else:
            result['stages']['real_sample'] = {'skipped': f'{sample} not found'}
        result['completed'] = True
        return result
    finally:
        (out / 'splat-import-source-gui.json').write_text(json.dumps(result, indent=2))
        qa.eval(f"import sys\nsys.modules.pop({FIXTURE_MODULE!r},None)\nresult=True")


if __name__ == '__main__':
    run_scenario('splat_import_source_gui_e2e', run)
