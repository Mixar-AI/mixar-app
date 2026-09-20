# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Run with runpy.run_path in an isolated QA app; then call finish().

Loads this checkout's archive code into the built app. A deterministic transport
fixture drives the real background writer, scene binding and RPC dispatch. No LLM
or scene mutation script is run. Redis/auth transport has separate backend tests.
Use the harness screenshot command afterward and inspect the image.
"""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import bpy
import mixar.modules.common

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / 'src/scripts/mixar/modules'
mixar.modules.common.__path__.insert(0, str(SOURCE / 'common'))


def load_checkout(name, relative):
    """Bind this checkout's module under its canonical name.

    The live app has already imported the bundled archive package, so the
    __path__ insert alone would keep serving the bundle's cached modules.
    """
    spec = importlib.util.spec_from_file_location(name, SOURCE / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    # `from . import store` resolves through the parent package attribute first.
    parent, _, leaf = name.rpartition('.')
    setattr(sys.modules[parent], leaf, module)
    return module


load_checkout('mixar.modules.common.agent_history.constants', 'common/agent_history/constants.py')
store = load_checkout('mixar.modules.common.agent_history.core.store', 'common/agent_history/core/store.py')
load_checkout('mixar.modules.common.agent_history.core.blobs', 'common/agent_history/core/blobs.py')
sync_module = load_checkout('mixar.modules.common.agent_history.core.qa_sync', 'common/agent_history/core/sync.py')
ArchiveSync = sync_module.ArchiveSync

archive_root = Path(tempfile.mkdtemp(prefix='mixar-history-qa-'))
store.root = lambda: archive_root
scene = bpy.context.scene
scene.mixie_session_id = 'archive-qa-session'
worker_scene = bpy.data.scenes.new('Archive QA private worker')
worker_scene.mixie_session_id = 'agentlane:' + 'b' * 64
initial_objects = sorted(ob.name for ob in bpy.data.objects)
record = {'version': 1, 'run_id': 'qa-run', 'task_id': 'worker', 'kind': 'message',
          'payload': {'id': 'qa-message', 'role': 'ai', 'text': 'Keep the doorway clear.',
                      'tool_calls': [{'name': 'execute_bpy_script', 'args': {'code': 'raise RuntimeError("ARCHIVE MUST NEVER EXECUTE THIS")'}}]}}
# Protocol v2: the image arrives as a reference; the archive thread "fetches" it
# through the stubbed HTTP transport, verifies it and rebuilds the original record.
image_bytes = b'\x89PNG qa-image ' * 64
image_record = {'version': 1, 'run_id': 'qa-run', 'task_id': 'worker', 'kind': 'image',
                'payload': {'id': hashlib.sha256(image_bytes).hexdigest()[:16], 'mime': 'image/png',
                            'label': 'render', 'kind': 'render', 'base64': base64.b64encode(image_bytes).decode()}}
referenced_payload = {k: v for k, v in image_record['payload'].items() if k != 'base64'}
referenced_payload['blob'] = {'seq': 2, 'bytes': len(image_bytes), 'sha256': hashlib.sha256(image_bytes).hexdigest()}
fetches = []
def fetch_stub(session_id, seq):
    fetches.append((session_id, seq))
    return image_bytes
sync_module.blobs.fetch_blob = fetch_stub
packet = {'session_id': scene.mixie_session_id, 'epoch': 'a' * 32, 'status': 'available',
          'records': [{'seq': 1, 'event_id': hashlib.sha256(store.canonical(record)).hexdigest(), 'record': record},
                      {'seq': 2, 'event_id': hashlib.sha256(store.canonical(image_record)).hexdigest(),
                       'record': {**image_record, 'payload': referenced_payload}}]}


class TransportFixture:
    is_connected = True
    agent_history_blobs_by_reference = True
    def __init__(self):
        self.requests = []
        self.responses = {}
        self._pending_callbacks = {}
        self._pending_deadlines = {}
        self._pending_lock = threading.Lock()
    def send_request(self, method, params, callback, timeout=20):
        assert method == 'agent.history_sync'
        assert scene.mixie_session_id in params['session_ids']
        assert worker_scene.mixie_session_id not in params['session_ids']
        assert params['blobs'] == 'reference'
        self.requests.append(params)
        callback({'version': 1, 'owner_id': 'qa-owner', 'sessions': [packet]})
        return 'qa-request'
    def queue_response(self, request_id, response):
        self.responses[request_id] = response


client = TransportFixture()
client._archive_sync = ArchiveSync(client)
client._archive_sync.start()
# Load the real current dispatch mixin without replacing the live app connection.
path = SOURCE / 'space_mixie_chat/core/socket_dispatch.py'
spec = importlib.util.spec_from_file_location('mixar.modules.space_mixie_chat.core.archive_qa_dispatch', path)
dispatch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dispatch)


def request_read():
    dispatch.SocketDispatch._handle_message(client, {'method': 'agent.history_read', 'id': 'qa-read',
        'params': {'owner_id': 'qa-owner', 'session_id': scene.mixie_session_id, 'message_id': 'qa-message'}})
    dispatch.SocketDispatch._handle_message(client, {'method': 'agent.history_read', 'id': 'qa-read-image',
        'params': {'owner_id': 'qa-owner', 'session_id': scene.mixie_session_id,
                   'image_id': image_record['payload']['id']}})


def finish():
    assert len(client.requests) >= 2
    assert client.requests[-1]['acknowledgements'][0]['seq'] == 2
    manifest = json.loads((archive_root / scene.mixie_session_id / 'manifest.json').read_text())
    assert manifest['scene_history_id'] == scene.mixar_op_history_id
    assert len((archive_root / scene.mixie_session_id / 'events/000001.jsonl').read_text().splitlines()) == 2
    assert client.responses['qa-read']['status'] == 'available'
    assert 'ARCHIVE MUST NEVER EXECUTE THIS' in client.responses['qa-read']['records'][0]['text']
    # v2: fetched once per delivery, stored as a verified separate blob, readable back.
    assert fetches and all(f == (scene.mixie_session_id, 2) for f in fetches)
    blob_path = archive_root / scene.mixie_session_id / 'blobs' / hashlib.sha256(image_bytes).hexdigest()
    assert blob_path.read_bytes() == image_bytes
    image = client.responses['qa-read-image']
    assert image['status'] == 'available' and base64.b64decode(image['image']['base64']) == image_bytes
    assert sorted(ob.name for ob in bpy.data.objects) == initial_objects
    assert client._archive_sync.last_error is None
    client._archive_sync.stop()
    bpy.data.scenes.remove(worker_scene)
    return {'ok': True, 'workspace_excluded': True, 'scene_linked': True, 'durable_ack': True, 'replay_deduplicated': True,
            'read_only_rpc': True, 'scene_unchanged': True, 'blob_by_reference': True}
