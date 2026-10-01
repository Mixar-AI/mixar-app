# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Regressions for incomplete folder context and non-durable attachments."""
import json
from types import SimpleNamespace

import pytest

from mixar.modules.context_folder.core import attach, indexer, manifest, reader, registry, rpc, grants
from mixar.modules.context_folder.core.errors import ContextFolderError


@pytest.fixture(autouse=True)
def isolated():
    indexer.clear_cache()
    grants.clear()
    yield
    indexer.clear_cache()
    grants.clear()


@pytest.mark.parametrize('names', [
    ['Refs', 'Refs', 'Refs (2)'],
    ['Refs (2)', 'Refs', 'Refs', 'Refs (3)', 'Refs'],
    ['a/b', 'a_b', 'a_b (2)', '', 'folder'],
    ['x' * 100, 'x' * 96, 'x' * 96 + ' (2)'],
])
def test_manifest_labels_are_unique_even_with_literal_suffixes(names):
    labels = manifest.unique_labels(names)
    assert len(set(labels)) == len(names)
    assert labels == manifest.unique_labels(names)


@pytest.mark.parametrize('length,truncated', [(23992, False), (23993, False), (23994, True), (30000, True)])
def test_read_reports_partial_single_line(tmp_path, length, truncated):
    (tmp_path / 'line.txt').write_text('x' * length)
    result = reader.read_text(tmp_path, 'line.txt')
    assert len(result['text']) <= 24000
    assert result['truncated'] is truncated
    assert result['end_line'] == result['total_lines'] == 1


def test_depth_pruning_marks_manifest_list_and_search_incomplete(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer, 'MAX_DEPTH', 1)
    (tmp_path / 'a' / 'b').mkdir(parents=True)
    (tmp_path / 'a' / 'found.txt').write_text('marker')
    (tmp_path / 'a' / 'b' / 'omitted.txt').write_text('marker')
    reg = registry.FolderRegistry(tmp_path / 'registry.json')
    monkeypatch.setattr(manifest, 'get_registry', lambda: reg)
    # Use the enclosing root to reach the depth boundary.
    fid = reg.register(tmp_path)
    assert manifest.describe_folder(fid, 'QA')['truncated']
    listing = reader.list_files(tmp_path)
    assert listing['index_truncated']
    assert 'a/b/omitted.txt' not in [f['path'] for f in listing['files']]
    assert reader.search(tmp_path, 'marker')['truncated']


def test_ignored_directories_at_depth_limit_are_not_truncation(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer, 'MAX_DEPTH', 0)
    (tmp_path / '.git').mkdir()
    assert not indexer.index_folder(tmp_path).truncated


@pytest.mark.parametrize('child', [False, True])
def test_walk_access_failure_is_never_reported_as_complete(tmp_path, monkeypatch, child):
    root = tmp_path / 'attached'
    root.mkdir()
    def denied_walk(path, *, onerror, **kwargs):
        if child:
            yield str(root), ['private'], []
        denied = root / 'private' if child else root
        onerror(PermissionError(13, 'denied', str(denied)))
    monkeypatch.setattr(indexer.os, 'walk', denied_walk)
    reg = registry.FolderRegistry(tmp_path / 'registry.json')
    monkeypatch.setattr(manifest, 'get_registry', lambda: reg)
    monkeypatch.setattr(rpc, 'get_registry', lambda: reg)
    fid = reg.register(root)
    grants.grant('qa', [fid])
    entry = manifest.describe_folder(fid, 'QA')
    reply = rpc.dispatch('context_folder.list', {'session_id': 'qa', 'folder_id': fid})
    if child:
        assert entry['available'] and entry['truncated']
        assert reply['success'] and reply['index_truncated']
    else:
        assert entry == {'folder_id': fid, 'name': 'QA', 'available': False}
        assert reply['error']['code'] == 'folder_unavailable'
    assert str(root) not in json.dumps(reply)


def test_registry_failure_rolls_back_and_attach_can_retry(tmp_path, monkeypatch):
    root = tmp_path / 'attached'
    root.mkdir()
    reg = registry.FolderRegistry(tmp_path / 'registry.json')
    save = reg._save
    def denied():
        raise PermissionError('synthetic write denial')
    monkeypatch.setattr(reg, '_save', denied)
    monkeypatch.setattr(attach, 'get_registry', lambda: reg)
    scene = SimpleNamespace(mixie_context_folders=[])
    result = attach.attach_folder(scene, str(root))
    assert not result['success']
    assert not scene.mixie_context_folders and not reg._load()
    assert str(root) not in json.dumps(result)
    with pytest.raises(ContextFolderError, match='Could not save'):
        reg.register(root)
    monkeypatch.setattr(reg, '_save', save)
    fid = reg.register(root)
    assert registry.FolderRegistry(reg.path).resolve(fid) == root
    assert reg.register(root) == fid
