# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Embedding manifests share the local catalog's exact identity and revisions."""

from . import service


def manifest():
    from ..library_enrollment import enrolled_names
    enrolled = enrolled_names()
    state = service.status()
    if state['indexing']:
        return None
    selected = [lib for lib in state['libraries'] if lib['name'] in enrolled]
    if any(lib['status'] in ('new', 'indexing') for lib in selected):
        if not state['indexing']:
            service.refresh()
        return None
    if any(lib['status'] != 'ready' for lib in selected):
        raise ValueError('An enrolled library is unavailable or incomplete; Refresh Libraries before training')
    if enrolled - {lib['name'] for lib in selected}:
        raise ValueError('An enrolled library is no longer configured; restore it or explicitly unenroll it')
    metadata = []
    with service.inventory() as catalog:
        for lib in selected:
            for row in catalog.records(lib['id']):
                hit = catalog.public({**row, 'library': lib['name'], 'status': lib['status']})
                metadata.append({k: hit[k] for k in
                                 ('name','library','blend_file','type','asset_id','revision')})
                metadata[-1]['source_id'] = catalog.source_id()
    return metadata


def enrich(infos, metadata):
    """Stamp rendered infos with the manifest's exact identity; upload what was indexed."""
    by_key = {(m['name'],m['library'],m['blend_file'],m['type']): m for m in metadata or []}
    for info in infos:
        blend_file = str(info.get('blend_file','')).replace('\\','/')
        row = by_key.get((info.get('name'),info.get('library'),blend_file,info.get('type')))
        if row is None:
            raise ValueError('Rendered asset differs from the indexed snapshot; refresh libraries and retry')
        info.update(blend_file=blend_file, asset_id=row['asset_id'],
                    revision=row['revision'], source_id=row['source_id'])
    return infos
