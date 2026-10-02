#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit model attachments: real native pickers, drops and scene imports.

Run in a fresh isolated Dev QA app with QA_HARNESS, MIXAR_QA_PORT and
QA_SCENARIO_OUT. Generates valid models through Blender's native exporters.
Inspect the screenshots alongside result.json; no message is sent.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA
from generation_reference_column_e2e import capture, pause, upload, open_picker
from reference_drop_ux_e2e import batch_drop, SCENE
from context_folder_checklist_e2e import dismiss_reports

FORMATS = ['obj', 'fbx', 'glb', 'gltf', 'usd', 'usda', 'usdc', 'usdz']
OP = 'MIXIE_CHAT_OT_add_image_from_file'


def state(qa):
    return qa.eval(f"s={SCENE}\nresult={{'objects':sorted(o.name for o in s.objects),"
                   "'selected':sorted(o.name for o in s.objects if o.select_get()),"
                   "'attachments':[(a.display_name,a.image_source,a.imported_object_names) "
                   "for a in s.mixie_chat_pending_attachments]}")


def run():
    qa = QA()
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/model-attachment-formats')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    assert qa.eval("import os\nresult=os.environ.get('MIXAR_QA')=='1'")
    assert not state(qa)['attachments'], 'Use a fresh app'
    # Fixture setup only: export one real mesh, then remove it before UI tests.
    qa.eval("bpy.ops.mesh.primitive_uv_sphere_add(segments=12,ring_count=8)\n"
            "o=bpy.context.object\no.name='FormatFixture'\nresult=True")
    paths = {}
    for ext in FORMATS:
        path = out / ('Model référence.' + ext)
        paths[ext] = path
        if ext == 'obj':
            expr = f'bpy.ops.wm.obj_export(filepath={str(path)!r},export_selected_objects=True)'
        elif ext == 'fbx':
            expr = f'bpy.ops.export_scene.fbx(filepath={str(path)!r},use_selection=True)'
        elif ext in ('glb', 'gltf'):
            fmt = 'GLB' if ext == 'glb' else 'GLTF_SEPARATE'
            expr = (f'bpy.ops.export_scene.gltf(filepath={str(path)!r},use_selection=True,'
                    f'use_active_scene=True,export_format={fmt!r})')
        else:
            expr = f'bpy.ops.wm.usd_export(filepath={str(path)!r},selected_objects_only=True)'
        assert 'FINISHED' in qa.eval(f'result=list({expr})'), ext
        assert path.stat().st_size > 0
    qa.eval("bpy.data.objects.remove(bpy.data.objects['FormatFixture'],do_unlink=True)\nresult=True")
    qa.open_chat()
    open_picker(qa, OP)
    qa.wait("bool(drv.find(area_type='FILE_BROWSER',prop='directory'))",timeout=8)
    glob = qa.eval("h=drv.find(area_type='FILE_BROWSER',prop='directory')[0]\n"
                   "result=h['_area'].spaces.active.params.filter_glob")
    assert all('*.' + ext in glob.split(';') for ext in FORMATS), glob
    qa.click(area_type='FILE_BROWSER',op='FILE_OT_cancel')
    pause(qa)
    assert not state(qa)['attachments']
    before = state(qa)
    for ext, path in paths.items():
        upload(qa, OP, path)
        current = state(qa)
        assert len(current['attachments']) == len(before['attachments']) + 1, (ext, current)
        name, source, roots = current['attachments'][-1]
        assert name == path.name and source == 'MODEL_FILE' and roots
        assert set(roots.split(',')) <= set(current['objects']) - set(before['objects'])
        assert current['selected'] == before['selected'], (ext, current)
        assert qa.eval(f'result=all(bpy.data.objects[n].type=="MESH" and '
                       f'len(bpy.data.objects[n].data.vertices)>20 for n in {roots.split(",")!r})')
        before = current
        print('PASS native picker ' + ext, flush=True)
    capture(qa, out, '01-model-attachments')
    # Same file via the picker and native multi-file drop must not reimport.
    upload(qa, OP, paths['fbx'])
    dismiss_reports(qa)
    assert state(qa) == before
    batch_drop(qa, [paths['fbx'], paths['glb']], chat=True)
    dismiss_reports(qa)
    assert state(qa) == before
    # Removing the pill leaves its mesh in the scene; a subsequent native
    # drop must actually import another copy, not just pass a duplicate test.
    for _ in FORMATS:
        qa.click(area_type='AGENT_BUBBLE',op='MIXIE_CHAT_OT_remove_attachment')
        pause(qa,.1)
    assert not state(qa)['attachments']
    assert state(qa)['objects'] == before['objects']
    batch_drop(qa, [paths['fbx'], paths['glb']], chat=True)
    current = state(qa)
    assert len(current['attachments']) == 2, current
    assert len(current['objects']) == len(before['objects']) + 2
    capture(qa, out, '02-native-model-drop')
    broken = out / 'broken.glb'
    broken.write_bytes(b'not a glTF file')
    batch_drop(qa, [broken], chat=True)
    dismiss_reports(qa)
    assert state(qa) == current
    # Frame an imported model in the actual scene for visual verification.
    qa.eval("w=drv.main_window()\na=next(a for a in w.screen.areas if a.type=='VIEW_3D')\n"
            "r=next(r for r in a.regions if r.type=='WINDOW')\n"
            "with bpy.context.temp_override(window=w,area=a,region=r):\n"
            "    bpy.ops.object.select_all(action='DESELECT')\n"
            f"    obj=bpy.data.objects[{current['attachments'][-1][2]!r}]\n"
            "    for other in w.scene.objects: other.hide_set(other != obj)\n"
            "    obj.select_set(True)\n    w.view_layer.objects.active=obj\n"
            "    bpy.ops.view3d.view_selected()\nresult=True")
    pause(qa,1)
    qa.cmd('snap',path=str(out/'03-imported-geometry.png'),area='VIEW_3D')
    result = {'passed':True,'formats':FORMATS,'picker_cancel':True,'duplicate_no_reimport':True,
              'native_drop':['fbx','glb'],'remove_keeps_geometry':True,
              'invalid_model_rejected':True,'selection_preserved':True,'paid_requests':0}
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    run()
