# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Isolated Blender catalog scanner. Never opens asset files in the user's Main."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import bpy


def digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_assets(path, relative, revision):
    """Read marked OBJECT/COLLECTION metadata, including full assemblies."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    with bpy.data.libraries.load(str(path), assets_only=True, link=False) as (src, dst):
        dst.objects = list(src.objects)
        dst.collections = list(src.collections)
    rows = []
    for kind, blocks in [('OBJECT', dst.objects), ('COLLECTION', dst.collections)]:
        for block in blocks:
            if block is None or block.asset_data is None:
                continue
            objects = list(block.all_objects) if kind == 'COLLECTION' else [block]
            # Instances of collections are valid scatter sources too.
            supported = any(o.type == 'MESH' or
                            (o.type == 'EMPTY' and o.instance_collection) for o in objects)
            meta = block.asset_data
            rows.append({'file': relative, 'kind': kind, 'name': block.name,
                         'revision': revision, 'metadata': {
                             'type': 'Collection' if kind == 'COLLECTION' else block.type,
                             'description': meta.description or '',
                             'tags': [t.name for t in meta.tags],
                             'author': meta.author or '', 'license': meta.license or '',
                             'scatterable': bool(supported)}})
    return rows


def run(plan):
    spec = importlib.util.spec_from_file_location('asset_catalog_store',
                                                 Path(__file__).with_name('store.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    catalog = mod.Catalog(plan['database'])
    failures = []
    try:
        for lib in plan['libraries']:
            root = Path(lib['root'])
            if not root.is_dir():
                catalog.status(lib['id'], 'offline', 'Library folder is unavailable')
                failures.append(lib['name'])
                continue
            prior = {}
            for row in catalog.records(lib['id']):
                prior.setdefault(row['file'], []).append(row)
            records, errors = [], []
            catalog.status(lib['id'], 'indexing')
            # os.walk's silent permission-error behavior is deliberately avoided.
            def files(folder):
                for entry in sorted(folder.iterdir()):
                    if entry.is_symlink():
                        continue
                    if entry.is_dir():
                        yield from files(entry)
                    elif entry.suffix.lower() == '.blend':
                        yield entry
            try:
                for path in files(root):
                    relative = path.relative_to(root).as_posix()
                    try:
                        before = path.stat()
                        revision = digest(path)
                        old = prior.get(relative, [])
                        rows = old if old and all(r['revision'] == revision for r in old) else read_assets(path, relative, revision)
                        after = path.stat()
                        if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                            raise ValueError('File changed while indexing')
                        records.extend(rows)
                    except Exception:
                        errors.append(relative)
            except OSError:
                errors.append('folder could not be read')
            if errors:
                # Preserve ALL prior rows: a partial snapshot is not a deletion list.
                catalog.status(lib['id'], 'partial', f'{len(errors)} files could not be indexed; retry Refresh')
                failures.append(lib['name'])
            else:
                catalog.replace(lib['id'], records)
        Path(plan['done']).write_text(json.dumps({'success': not failures, 'failed_libraries': failures}))
    finally:
        catalog.close()


if __name__ == '__main__':
    run(json.loads(Path(sys.argv[sys.argv.index('--') + 1]).read_text()))
