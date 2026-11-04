# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Additional real-app import and permission fixtures for the folder QA audit."""
import json
import os
from pathlib import Path
import bpy
from mixar.modules.context_folder.core import attach, grants, importer, indexer, reader, rpc


def run(root, scene):
    assert os.environ.get('MIXAR_QA')=='1'
    root=Path(root);out=[]
    def check(case,fn):
        try: out.append({'case':case,'status':'PASS','detail':fn()})
        except Exception as exc: out.append({'case':case,'status':'FAIL','detail':str(exc)})
    def mount(path):
        for fid in [item.folder_id for item in scene.mixie_context_folders]: attach.detach_folder(scene,fid)
        fid=attach.attach_folder(scene,str(path))['folder_id']
        attach.folder_context_for_send(scene,scene.mixie_session_id)
        return fid
    fid=mount(root/'05-Errors')
    def corrupt_model():
        before=set(o.name for o in scene.objects)
        r=importer.import_folder_file(scene.mixie_session_id,fid,'corrupt.glb')
        assert not r['success'],r
        assert set(o.name for o in scene.objects)==before
        assert str(root) not in json.dumps(r)
        return r
    check('13 corrupt model leaves scene intact',corrupt_model)
    extra=root/'11-Extra';extra.mkdir(exist_ok=True)
    (extra/'document.pdf').write_bytes(b'%PDF-1.4\n% QA unsupported-format fixture\n%%EOF')
    (extra/'tiny.hdr').write_bytes(b'#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 1 +X 1\n'+bytes([128,64,32,129]))
    fid=mount(extra)
    def formats():
        replies=[]
        for method,path,code in [('context_folder.read','document.pdf','not_text'),
                                 ('context_folder.view_image','tiny.hdr','preview_unsupported')]:
            r=rpc.dispatch(method,{'session_id':scene.mixie_session_id,'folder_id':fid,'path':path})
            assert r.get('error',{}).get('code')==code,r
            replies.append(r)
        r=importer.import_folder_file(scene.mixie_session_id,fid,'tiny.hdr')
        assert r['success'] and (r['width'],r['height'])==(1,1),r
        return replies+[r]
    check('unsupported document HDR preview and HDR import',formats)
    def blend():
        parent=bpy.data.objects.new('QA_Library_Parent',None)
        child=bpy.data.objects.new('QA_Library_Child',bpy.data.meshes.new('QA_Library_Mesh'))
        child.parent=parent
        bpy.data.libraries.write(str(extra/'qa_library.blend'),{parent,child})
        bpy.data.objects.remove(child);bpy.data.objects.remove(parent)
        r=importer.import_folder_file(scene.mixie_session_id,fid,'qa_library.blend')
        assert r['success'],r
        c=bpy.data.collections[r['collection']]
        assert len(c.objects)==2 and c in list(scene.collection.children),r
        parent=next(o for o in c.objects if o.parent is None)
        assert any(o.parent==parent for o in c.objects)
        assert bpy.data.filepath!=str(extra/'qa_library.blend')
        for o in list(c.objects): bpy.data.objects.remove(o,do_unlink=True)
        bpy.data.collections.remove(c)
        return r
    check('blend appends collection with parent hierarchy',blend)
    def permissions():
        private=extra/'unreadable';private.mkdir(exist_ok=True)
        (private/'secret.txt').write_text('synthetic access fixture')
        folder=mount(private)
        private.chmod(0)
        try:
            try:
                list(private.iterdir())
            except PermissionError:
                pass
            else:
                raise RuntimeError('INCONCLUSIVE: operating system did not deny directory access')
            indexer.clear_cache()
            r=attach.folder_context_for_send(scene,scene.mixie_session_id)['folders'][0]
            assert not (r.get('available') and r.get('file_count')==0),r
            return r
        finally:
            private.chmod(0o700)
    check('permission-denied folder is not reported empty',permissions)
    mount(root/'01-Hero-Project')
    return out
