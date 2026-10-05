# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Replayable archive idle benchmark; no auth, user history or scene mutations.

CLI: python3 tests/qa/agent_history_idle_probe.py
QA app: runpy.run_path(path)['run']() returns primitive timing/assertion results.
The uncached case follows the former full repair/write path for every empty poll.
All fixtures live under a TemporaryDirectory; module aliases isolate a live app's
archive worker. This is a CPU/disk microbenchmark, not whole-app latency evidence.
"""
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
import types


def _store():
    source = Path(__file__).resolve().parents[2] / 'src/scripts/mixar/modules/common/agent_history'
    package = types.ModuleType('mixar_archive_idle_probe')
    package.__path__ = [str(source)]
    sys.modules[package.__name__] = package
    name = package.__name__ + '.core.store'
    spec = importlib.util.spec_from_file_location(name, source / 'core/store.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run(sessions=8, rows=24000, rounds=3):
    store = _store()
    epoch = 'a' * 32
    timings = {}
    counters = {'tail_reads': 0, 'manifest_writes': 0}
    tail, atomic = store._tail, store._atomic
    def observed_tail(*args):
        counters['tail_reads'] += 1
        return tail(*args)
    def observed_atomic(path, raw):
        if path.name == 'manifest.json':
            counters['manifest_writes'] += 1
        return atomic(path, raw)
    store._tail, store._atomic = observed_tail, observed_atomic
    with tempfile.TemporaryDirectory(prefix='mixar-archive-idle-') as temporary:
        store.root = lambda: Path(temporary)
        packets = []
        record = {'version': 1, 'run_id': 'run', 'task_id': 'worker', 'kind': 'message',
                  'payload': {'id': 'fixture', 'role': 'tool', 'text': 'Synthetic idle fixture'}}
        import hashlib
        event_id = hashlib.sha256(store.canonical(record)).hexdigest()
        for index in range(sessions):
            session = 'fixture-%d' % index
            packet = {'session_id': session, 'epoch': epoch, 'status': 'available',
                      'records': [{'seq': 1, 'event_id': event_id, 'record': record}]}
            store.write_batch('qa-owner', packet)
            directory = store.root() / session
            journal = directory / 'events/000001.jsonl'
            row = json.loads(journal.read_text())
            with journal.open('wb') as handle:
                for seq in range(1, rows + 1):
                    handle.write(store.canonical({**row, 'seq': seq}) + b'\n')
            packets.append({**packet, 'records': []})
        journal_bytes = journal.stat().st_size
        for cached in (False, True):
            elapsed = []
            counters.update(tail_reads=0, manifest_writes=0)
            for _ in range(rounds):
                started = time.perf_counter()
                for packet in packets:
                    if not cached:
                        store.idle_cache.discard(store.root() / packet['session_id'])
                    ack = store.write_batch('qa-owner', packet)
                    assert ack['seq'] == rows
                elapsed.append(time.perf_counter() - started)
            timings['cached' if cached else 'uncached'] = {
                'median_seconds': statistics.median(elapsed), **counters}
        assert timings['cached']['tail_reads'] == 0
        assert timings['cached']['manifest_writes'] == 0
        # Genuine arrivals still validate, append, persist and acknowledge.
        incoming = {**packets[0], 'records': [{'seq': rows + 1, 'event_id': event_id, 'record': record}]}
        assert store.write_batch('qa-owner', incoming)['seq'] == rows + 1
        assert store.read('qa-owner', packets[0]['session_id'], limit=1)['status'] == 'available'
    return {'sessions': sessions, 'rows_per_journal': rows, 'journal_bytes': journal_bytes,
            'rounds': rounds, 'timings': timings, 'real_arrival_preserved': True,
            'isolated_temporary_archive': True}


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
