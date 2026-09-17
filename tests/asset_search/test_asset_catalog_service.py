# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Scan ownership is shared through the catalog file, not a per-process global.

The GUI, headless agent workers and QA runners all open the same SQLite catalog.
A process that did not start a scan must recognise a live one from another
process (report indexing, never reset it, never start a second scanner) and
must reclaim only a scan whose owner is gone.
"""
import os
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from mixar.modules.asset_search.core.catalog import service
from mixar.modules.asset_search.core.catalog.store import Catalog


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    path = tmp_path / 'catalog.db'
    (tmp_path / 'Biomes').mkdir()
    db = Catalog(path)
    lib = db.configure([{'name': 'Biomes', 'root': str(tmp_path / 'Biomes')}])[0]
    db.status(lib['id'], 'indexing')

    @contextmanager
    def inventory():
        opened = Catalog(path)
        try:
            yield opened
        finally:
            opened.close()
    monkeypatch.setattr(service, 'inventory', inventory)
    monkeypatch.setattr(service, '_job', None)
    monkeypatch.setattr(service, '_last_error', '')
    yield db
    db.close()


def _library(db):
    return db.libraries()[0]


def test_live_scan_of_another_process_is_reported_not_reset(catalog, monkeypatch):
    catalog.claim_scan(lambda: 4242)
    monkeypatch.setattr(service, 'pid_alive', lambda pid: pid == 4242)
    popen = []
    monkeypatch.setattr(service.subprocess, 'Popen', lambda *a, **k: popen.append(a))

    state = service.status()

    assert state['indexing'] is True
    assert _library(catalog)['status'] == 'indexing'
    assert service.refresh()['indexing'] is True and popen == []
    assert catalog.scan_owner()['pid'] == 4242


def test_dead_owner_is_reclaimed_and_its_libraries_marked_partial(catalog, monkeypatch):
    catalog.claim_scan(lambda: 4242)
    monkeypatch.setattr(service, 'pid_alive', lambda pid: False)

    state = service.status()

    assert state['indexing'] is False
    assert _library(catalog)['status'] == 'partial'
    assert 'interrupted' in _library(catalog)['message']
    assert catalog.scan_owner() is None


def test_expired_claim_counts_as_dead_even_if_the_pid_is_reused(catalog, monkeypatch):
    catalog.claim_scan(lambda: os.getpid())
    with catalog.db:
        catalog.db.execute("UPDATE settings SET value=json_set(value,'$.started',?) WHERE key='scan_owner'",
                           (time.time() - service.SCAN_DEADLINE - service.FOREIGN_SCAN_GRACE - 1,))

    assert service.status()['indexing'] is False
    assert catalog.scan_owner() is None


def test_refresh_claims_the_scan_for_other_processes(catalog, monkeypatch, tmp_path):
    monkeypatch.setattr(service, 'pid_alive', lambda pid: pid == 777)
    monkeypatch.setattr(service.tempfile, 'mkdtemp', lambda prefix: str(tmp_path / 'job'))
    (tmp_path / 'job').mkdir()
    proc = SimpleNamespace(pid=777, poll=lambda: None)
    monkeypatch.setattr(service.subprocess, 'Popen', lambda *a, **k: proc)
    monkeypatch.setattr(service.bpy.app, 'binary_path', 'blender')

    assert service.refresh()['indexing'] is True
    assert catalog.scan_owner()['pid'] == 777
    catalog.status(_library(catalog)['id'], 'indexing')  # what the spawned worker writes

    # Another process has no _job, yet must see the same scan.
    monkeypatch.setattr(service, '_job', None)
    assert service.status()['indexing'] is True
    assert _library(catalog)['status'] == 'indexing'


def test_claim_is_exclusive_and_released_by_owner_only(catalog):
    assert catalog.claim_scan(lambda: 1)['pid'] == 1
    assert catalog.claim_scan(lambda: 2) is None
    catalog.release_scan(2)
    assert catalog.scan_owner()['pid'] == 1
    catalog.release_scan(1)
    assert catalog.scan_owner() is None
    with pytest.raises(RuntimeError):
        catalog.claim_scan(lambda: (_ for _ in ()).throw(RuntimeError('spawn failed')))
    assert catalog.scan_owner() is None and catalog.libraries()  # connection still usable


def test_enrich_uploads_the_manifest_path_form():
    from mixar.modules.asset_search.core.catalog.training import enrich
    manifest = [{'name': 'Oak', 'library': 'Biomes', 'blend_file': 'trees/oak.blend', 'type': 'MESH',
                 'asset_id': 'asset', 'revision': 'sha', 'source_id': 'device'}]
    info = {'name': 'Oak', 'library': 'Biomes', 'blend_file': 'trees\\oak.blend', 'type': 'MESH'}
    assert enrich([info], manifest)[0]['blend_file'] == 'trees/oak.blend'
    assert info['asset_id'] == 'asset' and info['revision'] == 'sha'
    with pytest.raises(ValueError, match='refresh'):
        enrich([{**info, 'type': 'Collection'}], manifest)
