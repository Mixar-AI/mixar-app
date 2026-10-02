# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run via QA eval/runpy. Reproduce loss of gap metadata after manifest failure.

Loads the installed store as a separate module, isolates disk state, and fails
only the final manifest write after the gapped journal row has been fsynced.
Returns evidence in RESULT; no monkeypatch affects the live archive worker.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import uuid
from mixar.modules.common.agent_history.core import store as installed

spec = importlib.util.spec_from_file_location(
    'mixar.modules.common.agent_history.core.qa_gap_crash_probe', installed.__file__)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)
root = Path(os.environ['MIXAR_QA_OUT']) / ('gap-crash-' + uuid.uuid4().hex[:8])
store.root = lambda: root


def packet(seq):
    record = {'version': 1, 'run_id': 'qa-run', 'task_id': 'qa', 'kind': 'message',
              'payload': {'id': f'm{seq}', 'role': 'ai', 'text': f'row {seq}'}}
    return {'session_id': 'qa-gap-crash', 'epoch': 'a' * 32, 'status': 'available',
            'records': [{'seq': seq, 'record': record,
                         'event_id': hashlib.sha256(store.canonical(record)).hexdigest()}]}


store.write_batch('qa-owner', packet(1))
atomic = store._atomic


def fail_manifest(path, raw):
    if path.name == 'manifest.json' and json.loads(raw)['cursors'].get('a' * 32) == 4:
        raise OSError('QA injected final manifest write failure')
    return atomic(path, raw)


store._atomic = fail_manifest
try:
    store.write_batch('qa-owner', packet(4))
except OSError:
    pass
else:
    raise AssertionError('Fault injection was not reached')
finally:
    store._atomic = atomic
before = json.loads((root / 'qa-gap-crash/manifest.json').read_text())
rows = [json.loads(line)['seq'] for line in
        (root / 'qa-gap-crash/events/000001.jsonl').read_text().splitlines()]
ack = store.write_batch('qa-owner', packet(4))
after = json.loads((root / 'qa-gap-crash/manifest.json').read_text())
expected = {'epoch': 'a' * 32, 'reason': 'archive_sequence_gap', 'expected': 2, 'received': 4}
RESULT = {'journal_sequences': rows, 'before': before, 'retry_ack': ack,
          'after': after, 'expected_gap': expected, 'gap_survived': expected in after['gaps'],
          'root': str(root)}
(root / 'probe-result.json').write_text(json.dumps(RESULT, indent=2))

assert rows == [1, 4], rows
assert RESULT['gap_survived'], RESULT
