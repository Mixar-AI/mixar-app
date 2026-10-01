# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""In-app deterministic folder checklist. Executed by context_folder_checklist_e2e.

Uses copied fixtures and real bpy; each check records its own result so one
failure does not hide the rest. Never use on a non-QA instance.
"""
import base64
import io
import json
import os
import time
from pathlib import Path

import bpy
from PIL import Image
from mixar.modules.context_folder.core import attach, grants, indexer, manifest, reader, rpc
from mixar.modules.context_folder.core.registry import FolderRegistry, get_registry, set_registry_for_tests


def run_checks(root, scene):
    assert os.environ.get('MIXAR_QA') == '1'
    root = Path(root)
    hero = root / '01-Hero-Project'
    records = []

    def check(name, fn):
        started = time.monotonic()
        try:
            detail = fn()
            row = {'case': name, 'status': 'PASS', 'detail': detail}
        except Exception as exc:
            row = {'case': name, 'status': 'FAIL', 'detail': str(exc) or type(exc).__name__}
        row['seconds'] = round(time.monotonic() - started, 3)
        records.append(row)

    def require(condition, detail):
        assert condition, detail
        return detail

    def clean():
        for fid in [item.folder_id for item in scene.mixie_context_folders]:
            attach.detach_folder(scene, fid)

    def mount(path, sid='qa-audit'):
        clean()
        scene.mixie_session_id = sid
        result = attach.attach_folder(scene, str(path))
        assert result['success'], result
        context = attach.folder_context_for_send(scene, sid)
        return result['folder_id'], context

    folder_id, context = mount(hero)
    check('02 manifest and path privacy', lambda: require(
        context['folders'][0]['file_count'] == 12 and 'Lantern Plaza' in json.dumps(context)
        and str(root) not in json.dumps(context), context))
    check('03 nested line range', lambda: require(
        '    3  Secret test phrase: purple lantern 742' in reader.read_text(hero, 'nested/production/notes.txt',3,6)['text'],
        reader.read_text(hero, 'nested/production/notes.txt',3,6)))
    check('04 search case insensitive', lambda: require(
        reader.search(hero,'PURPLE LANTERN')['matches'][0]['line'] == 3,
        reader.search(hero,'PURPLE LANTERN')))
    check('05 unicode and empty text', lambda: require(
        'silver crane 318' in reader.read_text(hero,'nested/production/café 日本語 notes.txt')['text']
        and reader.read_text(hero,'nested/production/empty.txt')['total_lines'] == 0, 'Unicode marker and empty file correct'))

    def preview():
        result = reader.preview_image(hero, 'references/red-circle.png', 9999)
        image = Image.open(io.BytesIO(base64.b64decode(result['image_base64'])))
        assert image.size == (1024,768) and image.format == 'JPEG'
        assert (result['width'],result['height']) == (1600,1200)
        image.save(str(root.parent / 'rpc-preview.jpg'))
        return {'preview': image.size,'source':[result['width'],result['height']]}
    check('06 bounded image preview', preview)
    check('18 hidden and symlink omitted', lambda: require(
        not any(p['path'].startswith(('.', 'node_modules', 'outside-link')) for p in reader.list_files(hero)['files']),
        [p['path'] for p in reader.list_files(hero)['files']]))

    def denied_paths():
        for path in ['../10-Outside-Control/outside.txt','outside-link.txt','/etc/passwd','C:/Windows/win.ini',
                     r'\\server\share\x.txt','.hidden.txt','.git/config','node_modules/package/index.js']:
            reply = rpc.dispatch('context_folder.read',{'session_id':'qa-audit','folder_id':folder_id,'path':path})
            assert not reply['success'] and str(root) not in json.dumps(reply), (path, reply)
        for sid in ['', 'wrong-session']:
            assert not rpc.dispatch('context_folder.list',{'session_id':sid,'folder_id':folder_id})['success']
        return 'Traversal, absolute, UNC, hidden, dependency, symlink escape and wrong sessions refused'
    check('18 path refusal and session gate', denied_paths)

    def two_names():
        clean()
        for name in ['02-Team-A/Refs','03-Team-B/Refs']:
            assert attach.attach_folder(scene,str(root/name))['success']
        result = attach.folder_context_for_send(scene,'qa-audit')
        assert [f['name'] for f in result['folders']] == ['Refs','Refs (2)']
        values = [rpc.dispatch('context_folder.read',{'session_id':'qa-audit','folder_id':f['folder_id'],
                   'path':'nested/identity.txt'})['text'] for f in result['folders']]
        assert 'amber fox 111' in values[0] and 'teal owl 222' in values[1]
        return values
    check('10 same-name folders correct contents',two_names)

    def collision():
        assert attach.attach_folder(scene,str(root/'09-Name-Collision/Refs (2)'))['success']
        names = [f['name'] for f in attach.folder_context_for_send(scene,'qa-audit')['folders']]
        assert len(set(names)) == len(names), {'ambiguous_names':names}
        return names
    check('10 collision with literal suffixed name',collision)

    def limit():
        clean()
        names=['01-Hero-Project','02-Team-A/Refs','03-Team-B/Refs','04-Empty','05-Errors']
        for name in names:
            assert attach.attach_folder(scene,str(root/name))['success']
        extra=attach.attach_folder(scene,str(root/'06-Refresh-Move'))
        assert not extra['success'] and len(scene.mixie_context_folders)==5
        assert attach.attach_folder(scene,str(hero))['already'] and len(scene.mixie_context_folders)==5
        assert not attach.attach_folder(scene,'/')['success']
        assert not attach.attach_folder(scene,str(hero/'README.md'))['success']
        return '5 accepted; sixth/root/file rejected; duplicate at capacity remains idempotent'
    check('11 limit duplicate drive root and file',limit)
    check('12 empty folder',lambda:require(reader.list_files(root/'04-Empty')['total']==0,reader.list_files(root/'04-Empty')))

    error_id, _ = mount(root/'05-Errors')
    def failures():
        cases=[('context_folder.view_image','corrupt.png','unreadable_image'),
               ('context_folder.read','binary.txt','binary_file'),
               ('context_folder.read','oversized.txt','file_too_large'),
               ('context_folder.read','missing.txt','not_found')]
        replies=[]
        for method,path,code in cases:
            reply=rpc.dispatch(method,{'session_id':'qa-audit','folder_id':error_id,'path':path})
            assert reply.get('error',{}).get('code')==code,reply
            assert str(root) not in json.dumps(reply)
            replies.append(reply)
        return replies
    check('13 corrupt binary oversized missing',failures)
    def long_line():
        r=reader.read_text(root/'05-Errors','single-long-line.txt')
        detail={k:v for k,v in r.items() if k!='text'}
        detail['returned_chars']=len(r['text'])
        assert r['truncated'],detail
        return detail
    check('13 long single line reports truncation',long_line)

    def isolation():
        fid,_=mount(hero,'qa-A')
        other=bpy.data.scenes.new('QA-Folder-B')
        other.mixie_session_id='qa-B'
        try:
            assert not rpc.dispatch('context_folder.list',{'session_id':'qa-B','folder_id':fid})['success']
            attach.attach_folder(other,str(hero));attach.folder_context_for_send(other,'qa-B')
            attach.detach_folder(scene,fid)
            assert not rpc.dispatch('context_folder.list',{'session_id':'qa-A','folder_id':fid})['success']
            assert rpc.dispatch('context_folder.list',{'session_id':'qa-B','folder_id':fid})['success']
            attach.detach_folder(other,fid)
            assert not rpc.dispatch('context_folder.list',{'session_id':'qa-B','folder_id':fid})['success']
        finally:
            bpy.data.scenes.remove(other)
        return 'Real separate Scene attachments and per-session revocation verified'
    check('17 two scene isolation revocation',isolation)

    def unavailable():
        original=root/'06-Refresh-Move'; moved=root/'06-Refresh-Moved'
        fid,_=mount(original)
        original.rename(moved)
        try:
            snapshot=attach.folder_context_for_send(scene,'qa-audit')
            assert snapshot['folders'][0]['available'] is False
            assert rpc.dispatch('context_folder.read',{'session_id':'qa-audit','folder_id':fid,'path':'status.txt'})['error']['code']=='folder_unavailable'
        finally:
            moved.rename(original)
        assert rpc.dispatch('context_folder.read',{'session_id':'qa-audit','folder_id':fid,'path':'status.txt'})['success']
        return 'Move/unmount-equivalent unavailability and restore verified'
    check('14 moved folder recovery',unavailable)

    def large():
        _,snapshot=mount(root/'07-Large-Index')
        f=snapshot['folders'][0]
        pages=[reader.list_files(root/'07-Large-Index',offset=i,limit=200) for i in range(0,2000,200)]
        names=[e['path'] for p in pages for e in p['files']]
        assert len(names)==len(set(names))==2000 and pages[-1]['next_offset'] is None
        assert len(f['files'])==150 and f['truncated'] and f['file_count']==2000
        found=reader.search(root/'07-Large-Index','paginated-item')
        assert len(found['matches'])==60 and found['truncated']
        return {'indexed':len(names),'manifest':len(f['files']),'search_matches':len(found['matches']),'truncated':True}
    check('15 index manifest pagination search bounds',large)
    def depth():
        listing=reader.list_files(root/'08-Depth')
        assert len(listing['files'])==1 and listing['files'][0]['path'].endswith('at-depth-8.txt')
        assert listing['index_truncated'],listing
        return listing
    check('16 depth omission reports truncation',depth)

    def registry_missing():
        fid,_=mount(hero)
        original=get_registry()
        set_registry_for_tests(FolderRegistry(root.parent/'other-machine-registry.json'))
        try:
            result=manifest.build_folder_context(scene)
            assert result['folders'][0]['available'] is False,result
        finally:
            set_registry_for_tests(original)
        return 'Missing machine-local registry marks saved attachment unavailable'
    check('19 other-machine registry simulation',registry_missing)
    mount(hero)
    return records
