# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""In-app fixture for PR 1753; only transport and archive destinations are replaced."""
import base64
import copy
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import threading
import uuid

import bpy
from mixar.modules.common.agent_history.core import store, sync
from mixar.modules.common.notifications import get_notification_store
from mixar.modules.space_mixie_chat.core import chat_history
from mixar.modules.space_mixie_chat.core.socket_dispatch import SocketDispatch

assert os.environ.get('MIXAR_QA') == '1'
ROOT = Path(os.environ['MIXAR_QA_OUT']) / ('pr1753-' + uuid.uuid4().hex[:8])
ROOT.mkdir()
store.root = lambda: ROOT / 'archive'
chat_history._mixar_home = lambda: str(ROOT / 'chat')
chat_history.invalidate_cache()
SESSION = 'qa-history-' + uuid.uuid4().hex
EPOCH = 'a' * 32
OWNER = 'qa-owner'
TITLE = 'PR 1753 history recovery'
SCENE = bpy.context.scene
SCENE.mixie_session_id = SESSION
SCENE.mixar_op_history_id = 'scene-original'
chat_history.restore_into_scene(SCENE, {
    'session_id': SESSION,
    'messages': [{'sender': 'USER', 'message_type': 'USER', 'bubble_id': 'qa-user',
                  'content': TITLE},
                 {'sender': 'AGENT', 'message_type': 'AGENT', 'bubble_id': 'qa-agent',
                  'content': 'The archived conversation survives a change of scene.'}]})
assert chat_history.archive_current(SCENE)
INITIAL_OBJECTS = sorted(o.name for o in bpy.data.objects)


def packet(seq, session=SESSION, text=None, epoch=EPOCH):
    record = {'version': 1, 'run_id': 'qa-run', 'task_id': 'orchestrator',
              'kind': 'message', 'payload': {'id': f'm{seq}', 'role': 'ai',
              'text': text or f'Recovered archive record {seq}'}}
    return {'session_id': session, 'epoch': epoch, 'status': 'available',
            'records': [{'seq': seq, 'event_id': hashlib.sha256(store.canonical(record)).hexdigest(),
                         'record': record}]}


class Transport:
    is_connected = True
    agent_history_blobs_by_reference = False

    def __init__(self):
        self.requests = []
        self.responses = {}
        self.current = packet(1)
        self.lock = threading.Lock()

    def send_request(self, method, params, callback, timeout):
        assert method == 'agent.history_sync'
        with self.lock:
            self.requests.append(copy.deepcopy(params))
            outgoing = copy.deepcopy(self.current)
        callback({'version': 1, 'owner_id': OWNER, 'sessions': [outgoing]})
        return 'qa-history-request'

    def queue_response(self, request_id, response):
        self.responses[request_id] = response


transport = Transport()
worker = sync.ArchiveSync(transport)
transport._archive_sync = worker
# Shorten the fixture's idle polling only; scene capture and all validation are real.
worker._pause = lambda failures: worker.stop_event.wait(0.15)
log_text = io.StringIO()
log_handler = logging.StreamHandler(log_text)
logging.getLogger(sync.__name__).addHandler(log_handler)
get_notification_store().reset()
worker.start()


def manifest(session=SESSION):
    return json.loads((store.root() / session / 'manifest.json').read_text())


def acknowledged(seq):
    return any(any(a.get('session_id') == SESSION and a.get('seq') == seq
                   for a in r['acknowledgements']) for r in transport.requests)


def deliver(seq, corrupt=False):
    outgoing = packet(seq)
    if corrupt:
        outgoing['records'][0]['event_id'] = '0' * 64
    with transport.lock:
        transport.requests.clear()
        transport.current = outgoing
    return True


def switch_scene():
    global SCENE
    SCENE.mixie_session_id = ''
    SCENE = bpy.data.scenes.new('QA History Restored Scene')
    SCENE.mixar_op_history_id = 'scene-restored'
    for win in bpy.context.window_manager.windows:
        win.scene = SCENE
    return SCENE.name


def check(seq):
    value = manifest()
    assert value['cursors'][EPOCH] == seq, value
    assert acknowledged(seq), transport.requests[-2:]
    assert worker.last_error is None, worker.last_error
    assert value['scene_history_id'] == 'scene-original'
    assert sorted(o.name for o in bpy.data.objects) == INITIAL_OBJECTS
    return value


def read_rpc(seq):
    transport.responses.clear()
    for key, owner in [('valid', OWNER), ('wrong-owner', 'another-owner')]:
        SocketDispatch._handle_message(transport, {'method': 'agent.history_read', 'id': key,
            'params': {'owner_id': owner, 'session_id': SESSION, 'message_id': f'm{seq}'}})
    return True


def store_edges():
    checks = []
    def expect(code, fn):
        try:
            fn()
        except ValueError as exc:
            assert str(exc) == code, (code, str(exc))
        else:
            raise AssertionError('Accepted ' + code)
        checks.append(code)
    sid = 'qa-alias-cap'
    for seq in range(1, 24):
        store.write_batch(OWNER, packet(seq, sid), f'scene-{seq}')
    value = manifest(sid)
    assert value['scene_history_id'] == 'scene-1'
    assert value['scene_history_aliases'] == [f'scene-{i}' for i in range(8, 24)]
    store.write_batch(OWNER, packet(24, sid), 'scene-8')
    assert manifest(sid)['scene_history_aliases'] == [f'scene-{i}' for i in range(9, 24)] + ['scene-8']
    checks.append('aliases_bounded_unique_recent')
    sid = 'qa-invalid-scenes'
    for seq, scene_id in enumerate(['_nosession', '../invalid', '', None, 123, 'x' * 129], 1):
        store.write_batch(OWNER, packet(seq, sid), scene_id)
    assert manifest(sid)['scene_history_id'] is None
    store.write_batch(OWNER, packet(7, sid), 'real-scene')
    assert manifest(sid)['scene_history_id'] == 'real-scene'
    checks.append('invalid_scene_metadata_never_binds')
    sid = 'qa-gaps'
    store.write_batch(OWNER, packet(3, sid), 'a')
    store.write_batch(OWNER, packet(8, sid), 'b')
    store.write_batch(OWNER, packet(8, sid), 'b')
    gaps = manifest(sid)['gaps']
    assert [(g['expected'], g['received']) for g in gaps] == [(1, 3), (4, 8)]
    assert len((store.root() / sid / 'events/000001.jsonl').read_text().splitlines()) == 2
    checks.append('initial_multiple_gaps_and_replay_deduplication')
    expect('archive_replay_conflict', lambda: store.write_batch(OWNER, packet(8, sid, 'different')))
    expect('archive_owner_or_version_mismatch', lambda: store.write_batch('intruder', packet(9, sid)))
    bad = packet(9, sid); bad['records'][0]['record']['version'] = 99
    bad['records'][0]['event_id'] = hashlib.sha256(store.canonical(bad['records'][0]['record'])).hexdigest()
    expect('unsupported_archive_version', lambda: store.write_batch(OWNER, bad))
    expect('invalid_archive_id', lambda: store.write_batch(OWNER, packet(1, '../escape')))
    store.write_batch(OWNER, packet(1, sid, epoch='b' * 32))
    assert manifest(sid)['gaps'][-1]['reason'] == 'delivery_epoch_changed'
    checks.append('epoch_rollover')
    sid = 'qa-image-gap'
    raw = b'archive fixture image'
    p = packet(4, sid)
    record = p['records'][0]['record']
    record['kind'] = 'image'
    record['payload'] = {'id': hashlib.sha256(raw).hexdigest()[:16], 'mime': 'image/png',
                         'base64': base64.b64encode(raw).decode()}
    p['records'][0]['event_id'] = hashlib.sha256(store.canonical(record)).hexdigest()
    store.write_batch(OWNER, p)
    result = store.read(OWNER, sid, image_id=record['payload']['id'])
    assert base64.b64decode(result['image']['base64']) == raw
    checks.append('inline_image_after_gap')
    assert sync._reason(ValueError('/secret/private payload')) == 'ValueError'
    assert sync._reason(ValueError('archive_record_hash_mismatch')) == 'archive_record_hash_mismatch'
    checks.append('log_reason_redaction')
    return checks


def finish():
    worker.stop()
    logging.getLogger(sync.__name__).removeHandler(log_handler)
    return {'root': str(ROOT), 'log': log_text.getvalue(), 'objects_unchanged':
            sorted(o.name for o in bpy.data.objects) == INITIAL_OBJECTS}
