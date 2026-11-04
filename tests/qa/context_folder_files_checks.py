# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real-app checks for single-file context attachments (run inside the QA app).

Attaches a rendered clip, a text note and a PDF as context FILES (no folder),
then proves the chips, the synthetic ``Attached files`` manifest folder, the
RPCs through its set id (read / view_video / list / errors) and detachment.
Leaves ``clip.mp4`` and ``brief.pdf`` attached for the driver's UI checks.
"""
import importlib.util
import json
import os
from pathlib import Path

ATTACHED = 'Attached files'


def _video_checks():
    spec = importlib.util.spec_from_file_location(
        'folder_video_checks', str(Path(__file__).with_name('context_folder_video_checks.py')))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(out_dir, scene):
    assert os.environ.get('MIXAR_QA') == '1'
    from mixar.modules.context_folder.core import attach, files, rpc
    out = Path(out_dir)
    fixtures = out / 'fixtures' / 'files'
    fixtures.mkdir(parents=True, exist_ok=True)
    rows = []

    def check(case, fn):
        try:
            rows.append({'case': case, 'status': 'PASS', 'detail': fn()})
        except Exception as exc:  # noqa: BLE001 — a failure is a row, never an abort
            rows.append({'case': case, 'status': 'FAIL', 'detail': repr(exc)})
        (out / 'files-checklist.json').write_text(json.dumps(rows, indent=2, default=str))

    session_id = scene.mixie_session_id or 'qa-context-files-session'
    state = {}

    def clean():
        for fid in [item.folder_id for item in scene.mixie_context_folders]:
            attach.detach_folder(scene, fid)
        for fid in [item.file_id for item in scene.mixie_context_files]:
            files.detach_file(scene, fid)
    clean()

    def fixture():
        clip = _video_checks().render_fixture(scene, fixtures)
        (fixtures / 'notes.txt').write_text('Hero: a knight in green armour.\nHeight 1.8 m.\n')
        (fixtures / 'brief.pdf').write_bytes(b'%PDF-1.4\n% QA fixture\n%%EOF')
        (fixtures / '.secret').write_text('never shared')
        state['clip'] = clip
        return {'clip_bytes': clip.stat().st_size}
    check('01 fixtures rendered and written', fixture)

    def attach_three():
        results = [files.attach_file(scene, str(fixtures / name)) for name in ('clip.mp4', 'notes.txt', 'brief.pdf')]
        assert all(r['success'] and not r['already'] for r in results), results
        assert [r['kind'] for r in results] == ['video', 'text', 'document'], results
        again = files.attach_file(scene, str(fixtures / 'clip.mp4'))
        assert again['success'] and again['already'], again
        hidden = files.attach_file(scene, str(fixtures / '.secret'))
        assert not hidden['success'], hidden
        folder = files.attach_file(scene, str(fixtures))
        assert not folder['success'], folder
        assert len(scene.mixie_context_files) == 3
        assert scene.mixie_context_files_id
        state['set_id'] = scene.mixie_context_files_id
        return {'names': [i.name for i in scene.mixie_context_files], 'set_id_len': len(state['set_id'])}
    check('02 attach clip/note/pdf; duplicate, hidden and directory refused', attach_three)

    def manifest():
        ctx = attach.folder_context_for_send(scene, session_id)
        entry = ctx['folders'][-1]
        assert entry['name'] == ATTACHED and entry['available'], entry
        assert entry['folder_id'] == state['set_id']
        assert entry['kinds'] == {'video': 1, 'text': 1, 'document': 1}, entry['kinds']
        assert sorted(f['path'] for f in entry['files']) == ['brief.pdf', 'clip.mp4', 'notes.txt']
        text = json.dumps(ctx)
        assert str(fixtures) not in text and str(out) not in text
        return {'folders': len(ctx['folders']), 'kinds': entry['kinds']}
    check('03 manifest carries one path-free "Attached files" folder, listed last', manifest)

    def params(**extra):
        return {'session_id': session_id, 'folder_id': state['set_id'], **extra}

    def rpcs():
        read = rpc.dispatch('context_folder.read', params(path='notes.txt'))
        assert read.get('success') and 'green armour' in read['text'], read
        video = rpc.dispatch('context_folder.view_video', params(path='clip.mp4', count=2))
        assert video.get('success') and len(video['frames']) == 2, video.get('error')
        listing = rpc.dispatch('context_folder.list', params())
        assert listing.get('success') and listing['total'] == 3, listing
        search = rpc.dispatch('context_folder.search', params(query='knight'))
        assert search.get('success') and search['matches'], search
        return {'read_lines': read['total_lines'], 'frames': [f['frame_index'] for f in video['frames']],
                'listed': listing['total']}
    check('04 read / view_video / list / search work through the set id', rpcs)

    def errors():
        got = {}
        for label, p, method, code in [
            ('pdf as text', params(path='brief.pdf'), 'read', 'not_text'),
            ('note as video', params(path='notes.txt'), 'view_video', 'not_video'),
            ('missing member', params(path='nope.mp4'), 'view_video', 'not_found'),
            ('traversal', params(path='../notes.txt'), 'read', 'invalid_path'),
            ('foreign session', {**params(path='notes.txt'), 'session_id': 'other'}, 'read', 'folder_not_attached'),
        ]:
            r = rpc.dispatch('context_folder.' + method, p)
            assert not r.get('success') and r['error']['code'] == code, (label, r)
            assert str(fixtures) not in json.dumps(r), (label, r)
            got[label] = code
        return got
    check('05 error codes are specific and path-free', errors)

    def detach():
        note_id = next(i.file_id for i in scene.mixie_context_files if i.name == 'notes.txt')
        assert files.detach_file(scene, note_id)
        r = rpc.dispatch('context_folder.read', params(path='notes.txt'))
        assert r['error']['code'] == 'not_found', r
        ctx = attach.folder_context_for_send(scene, session_id)
        assert sorted(f['path'] for f in ctx['folders'][-1]['files']) == ['brief.pdf', 'clip.mp4']
        return {'remaining': [i.name for i in scene.mixie_context_files]}
    check('06 detaching a file revokes it at once and shrinks the manifest', detach)
    return rows
