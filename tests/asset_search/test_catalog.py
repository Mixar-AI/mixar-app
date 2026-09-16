# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
import pytest
from mixar.modules.asset_search.core.catalog.store import Catalog, fuse


@pytest.fixture
def catalog(tmp_path):
    db = Catalog(tmp_path / 'catalog.db')
    roots = [tmp_path / name for name in ('Biomes', 'Props')]
    for root in roots:
        root.mkdir()
        (root / 'oak.blend').write_bytes(b'asset')
    libraries = db.configure([{'name': root.name, 'root': str(root)} for root in roots])
    for lib in libraries:
        db.replace(lib['id'], [{'file': 'oak.blend', 'kind': 'COLLECTION', 'name': 'Oak',
            'revision': 'v1', 'metadata': {'tags': ['tree', 'deciduous'],
            'description': 'An autumn forest tree', 'scatterable': True}},
            {'file': 'oak.blend', 'kind': 'OBJECT', 'name': 'Oak', 'revision': 'v1',
             'metadata': {'tags': ['tree'], 'scatterable': True}}])
    yield db
    db.close()


def test_same_names_and_datablock_kinds_remain_distinct(catalog):
    hits = catalog.search('oak')
    assert len(hits) == 4
    assert len({h['asset_id'] for h in hits}) == 4
    assert all('root' not in h and 'path' not in h for h in hits)


def test_tags_and_library_filter(catalog):
    hits = catalog.search('deciduous', ['Biomes'], scatterable=True)
    assert len(hits) == 1 and hits[0]['kind'] == 'COLLECTION'
    assert catalog.search('anything', ['unknown']) == []


def test_revision_changes_invalidate_old_result_without_changing_identity(catalog):
    hit = catalog.search('deciduous', ['Biomes'])[0]
    rows = catalog.records(hit['library_id'])
    for row in rows:
        row['revision'] = 'v2'
    catalog.replace(hit['library_id'], rows)
    updated = catalog.search('deciduous', ['Biomes'])[0]
    assert updated['asset_id'] == hit['asset_id']
    with pytest.raises(ValueError, match='changed'):
        catalog.resolve(hit['asset_id'], 'v1')


def test_offline_status_preserves_inventory(catalog):
    hit = catalog.search('deciduous', ['Biomes'])[0]
    catalog.status(hit['library_id'], 'offline', 'unavailable')
    found = catalog.search('deciduous', ['Biomes'])
    assert len(found) == 1 and not found[0]['available']
    assert len(catalog.records(hit['library_id'])) == 2


def test_disabled_library_cannot_be_resolved(catalog):
    hit = catalog.search('deciduous', ['Biomes'])[0]
    catalog.configure([])
    assert catalog.search('oak') == []
    with pytest.raises(ValueError, match='configured'):
        catalog.resolve(hit['asset_id'], 'v1')


def test_snapshot_replace_rolls_back_on_invalid_row(catalog):
    hit = catalog.search('deciduous', ['Biomes'])[0]
    with pytest.raises(KeyError):
        catalog.replace(hit['library_id'], [{'file': 'broken'}])
    assert len(catalog.search('oak')) == 4


def test_semantic_hits_are_resolved_locally_and_kind_aware(catalog):
    candidates = [{'score': .9, 'metadata': {'name': 'Oak', 'library': 'Biomes',
                   'blend_file': 'oak.blend', 'type': 'Collection'}},
                  {'score': 1, 'metadata': {'name': 'Missing', 'library': 'Biomes'}}]
    hits = catalog.match(candidates)
    assert len(hits) == 1 and hits[0]['kind'] == 'COLLECTION'
    assert not catalog.match(candidates, ['Props'])
    assert len(fuse(hits, hits)) == 1


def test_query_is_not_fts_code(catalog):
    assert catalog.search('" OR * NEAR(,,') == []


def test_semantic_hits_reject_other_computers_and_stale_content(catalog):
    meta = {'name': 'Oak', 'library': 'Biomes', 'blend_file': 'oak.blend',
            'type': 'Collection', 'revision': 'v1', 'source_id': catalog.source_id()}
    assert len(catalog.match([{'metadata': meta}])) == 1
    assert catalog.match([{'metadata': {**meta, 'source_id': 'another-computer'}}]) == []
    assert catalog.match([{'metadata': {**meta, 'revision': 'old-content'}}]) == []
    assert catalog.source_id() == meta['source_id']


def test_worker_preserves_complete_snapshot_when_one_file_fails(catalog, monkeypatch, tmp_path):
    from mixar.modules.asset_search.core.catalog import worker
    lib = next(l for l in catalog.libraries(private=True) if l['name'] == 'Biomes')
    before = catalog.records(lib['id'])
    (tmp_path / 'Biomes' / 'broken.blend').write_bytes(b'not a blend file')
    def unreadable(*args):
        raise OSError('unreadable asset')
    monkeypatch.setattr(worker, 'read_assets', unreadable)
    database = catalog.db.execute('PRAGMA database_list').fetchone()[2]
    worker.run(dict(database=database, libraries=[lib], done=str(tmp_path/'done.json')))
    assert catalog.records(lib['id']) == before
    assert next(l for l in catalog.libraries() if l['id'] == lib['id'])['status'] == 'partial'


def test_worker_offline_is_not_a_deletion_list(catalog, tmp_path):
    from mixar.modules.asset_search.core.catalog import worker
    lib = next(l for l in catalog.libraries(private=True) if l['name'] == 'Biomes')
    (tmp_path/'Biomes').rename(tmp_path/'unmounted')
    database = catalog.db.execute('PRAGMA database_list').fetchone()[2]
    worker.run(dict(database=database, libraries=[lib], done=str(tmp_path/'done.json')))
    assert len(catalog.records(lib['id'])) == 2
    assert next(l for l in catalog.libraries() if l['id'] == lib['id'])['status'] == 'offline'
