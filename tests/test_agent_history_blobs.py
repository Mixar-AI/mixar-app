# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Protocol v2 image references are fetched, verified and rebuilt before archiving."""
import base64
import hashlib
import importlib
import json
import sys
import types
from pathlib import Path

import pytest


@pytest.fixture
def blobs(monkeypatch):
    root = Path(__file__).resolve().parents[1] / 'src/scripts/mixar/modules/common/agent_history'
    package = types.ModuleType('archive_blobs_fixture')
    package.__path__ = [str(root)]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    return importlib.import_module(package.__name__ + '.core.blobs')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def referenced(raw, seq=2):
    inline = {'version': 1, 'run_id': 'run', 'task_id': 'task', 'kind': 'image',
              'payload': {'id': hashlib.sha256(raw).hexdigest()[:16], 'mime': 'image/png',
                          'base64': base64.b64encode(raw).decode()}}
    event_id = hashlib.sha256(canonical(inline)).hexdigest()
    payload = {k: v for k, v in inline['payload'].items() if k != 'base64'}
    payload['blob'] = {'seq': seq, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    return inline, {'session_id': 'conversation', 'epoch': 'a' * 32, 'status': 'available',
                    'records': [{'seq': seq, 'event_id': event_id, 'record': {**inline, 'payload': payload}}]}


def test_fetched_bytes_rebuild_the_original_record(blobs):
    raw = b'\x89PNG' * 100
    inline, packet = referenced(raw)
    calls = []
    def fetch(session, seq):
        calls.append((session, seq))
        return raw
    blobs.materialize(packet, fetch=fetch)
    assert calls == [('conversation', 2)]
    record = packet['records'][0]['record']
    assert record == inline
    assert hashlib.sha256(canonical(record)).hexdigest() == packet['records'][0]['event_id']


def test_text_records_are_untouched_and_never_fetched(blobs):
    packet = {'session_id': 'conversation', 'records': [{'seq': 1, 'event_id': 'x', 'record': {
        'version': 1, 'run_id': 'r', 'task_id': 't', 'kind': 'message', 'payload': {'id': 'm', 'text': 'hi'}}}]}
    before = json.loads(json.dumps(packet))
    blobs.materialize(packet, fetch=lambda *a: pytest.fail('fetched'))
    assert packet == before


@pytest.mark.parametrize('tamper', [
    lambda ref, raw: raw + b'x',                      # length mismatch
    lambda ref, raw: b'z' * len(raw),                 # digest mismatch
])
def test_corrupt_bytes_are_refused(blobs, tamper):
    raw = b'pixels' * 50
    _, packet = referenced(raw)
    ref = packet['records'][0]['record']['payload']['blob']
    with pytest.raises(blobs.BlobUnavailable, match='hash_mismatch') as failure:
        blobs.materialize(packet, fetch=lambda s, q: tamper(ref, raw))
    assert failure.value.index == 0


@pytest.mark.parametrize('descriptor', [
    'not-a-dict', {'seq': 0, 'bytes': 1, 'sha256': 'a' * 64}, {'seq': 1, 'bytes': -1, 'sha256': 'a' * 64},
    {'seq': 1, 'bytes': 1, 'sha256': 'short'}, {'seq': True, 'bytes': 1, 'sha256': 'a' * 64},
    {'seq': 1, 'bytes': 9 * 1024 * 1024, 'sha256': 'a' * 64}, {'seq': 1, 'bytes': 0, 'sha256': 'a' * 64},
])
def test_invalid_descriptors_are_refused_before_any_fetch(blobs, descriptor):
    _, packet = referenced(b'x')
    packet['records'][0]['record']['payload']['blob'] = descriptor
    with pytest.raises(blobs.BlobUnavailable, match='descriptor_invalid'):
        blobs.materialize(packet, fetch=lambda *a: pytest.fail('fetched'))


def test_http_failure_is_blob_unavailable_with_the_network_contract(blobs, monkeypatch):
    from mixar.modules.common.api import exceptions
    cause = OSError('connection reset')
    def get(endpoint, params, timeout):
        raise exceptions.ConnectionError('Failed to connect') from cause
    monkeypatch.setitem(sys.modules, 'mixar.modules.common.api.client',
                        types.SimpleNamespace(get_http_client=lambda: types.SimpleNamespace(get=get)))
    logged = []
    monkeypatch.setitem(sys.modules, 'mixar.modules.common.network', types.SimpleNamespace(
        classify_network_error=lambda exc, url=None: ('failure', exc),
        log_network_failure=lambda logger, failure, context: logged.append((failure, context))))
    with pytest.raises(blobs.BlobUnavailable):
        blobs.fetch_blob('conversation', 2)
    # The classifier walks __cause__ itself; it must receive the wrapper with its chain intact.
    assert logged and isinstance(logged[0][0][1], exceptions.ConnectionError) and logged[0][0][1].__cause__ is cause


def test_fetch_returns_raw_body_bytes(blobs, monkeypatch):
    def get(endpoint, params, timeout):
        assert endpoint == blobs.ENDPOINT and params == {'session_id': 'conversation', 'seq': 2}
        return types.SimpleNamespace(raw=types.SimpleNamespace(content=b'bytes'))
    monkeypatch.setitem(sys.modules, 'mixar.modules.common.api.client',
                        types.SimpleNamespace(get_http_client=lambda: types.SimpleNamespace(get=get)))
    assert blobs.fetch_blob('conversation', 2) == b'bytes'


def test_non_image_records_with_a_blob_key_are_left_alone(blobs):
    packet = {'session_id': 'conversation', 'records': [{'seq': 1, 'event_id': 'x', 'record': {
        'version': 1, 'run_id': 'r', 'task_id': 't', 'kind': 'message', 'payload': {'id': 'm', 'blob': 'x'}}}]}
    before = json.loads(json.dumps(packet))
    blobs.materialize(packet, fetch=lambda *a: pytest.fail('fetched'))
    assert packet == before


def test_failure_index_points_past_the_completed_records(blobs):
    raw = b'ok' * 40
    _, first = referenced(raw, seq=1)
    _, second = referenced(raw, seq=2)
    packet = {'session_id': 'conversation', 'records': first['records'] + second['records']}
    def fetch(session, seq):
        if seq == 2:
            raise blobs.BlobUnavailable('NotFoundError')
        return raw
    with pytest.raises(blobs.BlobUnavailable) as failure:
        blobs.materialize(packet, fetch=fetch)
    assert failure.value.index == 1
    assert 'base64' in packet['records'][0]['record']['payload']  # first record is complete


def test_should_stop_interrupts_between_records(blobs):
    raw = b'ok' * 40
    _, first = referenced(raw, seq=1)
    _, second = referenced(raw, seq=2)
    packet = {'session_id': 'conversation', 'records': first['records'] + second['records']}
    calls = []
    with pytest.raises(blobs.BlobUnavailable, match='stopped') as failure:
        blobs.materialize(packet, fetch=lambda s, q: calls.append(q) or raw, should_stop=lambda: len(calls) == 1)
    assert calls == [1] and failure.value.index == 1


def test_http_status_failure_is_logged_with_its_code(blobs, monkeypatch, caplog):
    import logging
    from mixar.modules.common.api import exceptions
    def get(endpoint, params, timeout):
        raise exceptions.NotFoundError('gone', status_code=404)
    monkeypatch.setitem(sys.modules, 'mixar.modules.common.api.client',
                        types.SimpleNamespace(get_http_client=lambda: types.SimpleNamespace(get=get, _base_url='https://x')))
    with caplog.at_level(logging.WARNING), pytest.raises(blobs.BlobUnavailable, match='NotFoundError'):
        blobs.fetch_blob('conversation', 2)
    assert 'status=404' in caplog.text and 'gone' not in caplog.text


def test_fetch_prefers_binary_data_from_the_shared_client(blobs, monkeypatch):
    def get(endpoint, params, timeout):
        return types.SimpleNamespace(data=b'binary', raw=types.SimpleNamespace(content=b'binary'))
    monkeypatch.setitem(sys.modules, 'mixar.modules.common.api.client',
                        types.SimpleNamespace(get_http_client=lambda: types.SimpleNamespace(get=get)))
    assert blobs.fetch_blob('conversation', 2) == b'binary'
