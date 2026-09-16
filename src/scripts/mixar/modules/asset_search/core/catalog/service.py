# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Client catalog lifecycle. Main-thread entry points; scanning runs out of process."""

import atexit
import json
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import bpy

from .store import Catalog, fuse

_job = None
_last_error = ''


def shutdown():
    """Process teardown only; Blender data is already freed during atexit."""
    global _job
    if _job:
        proc, folder, _ = _job
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        shutil.rmtree(folder, ignore_errors=True)
        _job = None


atexit.register(shutdown)


@contextmanager
def inventory():
    base = bpy.utils.user_resource('CONFIG', path='mixar', create=True)
    catalog = Catalog(Path(base) / 'asset_catalog.sqlite3')
    try:
        # Headless agent workers start with factory preferences. They read the
        # GUI's catalog; an empty worker preference list must not disable it.
        if not bpy.app.background:
            catalog.configure([{'name': lib.name, 'root': bpy.path.abspath(lib.path)}
                               for lib in bpy.context.preferences.filepaths.asset_libraries if lib.path])
        yield catalog
    finally:
        catalog.close()


def status():
    global _job, _last_error
    if _job:
        proc, folder, started = _job
        elapsed = time.monotonic() - started
        expired = elapsed > 900
        if expired and proc.poll() is None:
            proc.kill() if elapsed > 905 else proc.terminate()
        if proc.poll() is not None:
            done = Path(folder) / 'done.json'
            try:
                result = json.loads(done.read_text())
            except (OSError, ValueError):
                result = None
            if result is None:
                _last_error = 'Library scan stopped; Refresh to retry. Existing assets were preserved.'
                with inventory() as catalog:
                    for lib in catalog.libraries():
                        if lib['status'] == 'indexing':
                            catalog.status(lib['id'], 'partial', _last_error)
            else:
                _last_error = '' if result['success'] else 'Some libraries are unavailable; their last index was preserved.'
            shutil.rmtree(folder, ignore_errors=True)
            _job = None
    with inventory() as catalog:
        if _job is None:
            for lib in catalog.libraries():
                if lib['status'] == 'indexing':
                    catalog.status(lib['id'], 'partial', 'Previous scan was interrupted; Refresh to retry')
        return {'schema_version': 1, 'indexing': _job is not None,
                'source_id': catalog.source_id(),
                'libraries': catalog.libraries(), 'message': _last_error}


def refresh():
    global _job, _last_error
    current = status()
    if current['indexing']:
        return current
    with inventory() as catalog:
        libs = catalog.libraries(private=True)
        database = catalog.db.execute('PRAGMA database_list').fetchone()[2]
    if not libs:
        return current
    folder = tempfile.mkdtemp(prefix='mixar_catalog_')
    plan = Path(folder) / 'plan.json'
    plan.write_text(json.dumps({'database': database, 'libraries': libs,
                               'done': str(Path(folder) / 'done.json')}))
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    try:
        with open(Path(folder) / 'worker.log', 'w') as log:
            proc = subprocess.Popen([bpy.app.binary_path, '-b', '--factory-startup',
                '--disable-autoexec', '--python', str(Path(__file__).with_name('worker.py')),
                '--', str(plan)], stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
        _job = (proc, folder, time.monotonic())
        _last_error = ''
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise RuntimeError('Could not start library indexing; try Refresh again') from None
    return status()


def search(query='', libraries=None, limit=20, scatterable=False, semantic_candidates=None):
    if libraries is not None and (not isinstance(libraries, list) or
                                  any(not isinstance(x, str) for x in libraries)):
        raise ValueError('libraries must be a list of library names or IDs')
    limit = max(1, min(int(limit), 100))
    state = status()
    if any(lib['status'] == 'new' for lib in state['libraries']) and not state['indexing']:
        state = refresh()
    with inventory() as catalog:
        lexical = catalog.search(query, libraries, limit, scatterable)
        semantic = catalog.match(semantic_candidates or [], libraries)
        if scatterable:
            semantic = [h for h in semantic if h['scatterable']]
        hits = fuse(lexical, semantic, limit)
    selected = [lib for lib in state['libraries']
                if not libraries or lib['name'] in libraries or lib['id'] in libraries]
    if selected and all(lib['status'] == 'ready' for lib in selected):
        state['message'] = ''
    elif libraries and not selected:
        state['message'] = 'No configured library matches this filter'
    return {**state, 'query': query, 'results': hits,
            'search_mode': 'hybrid' if semantic else 'name_tags_description'}


def resolve(asset_id, revision):
    with inventory() as catalog:
        return catalog.resolve(asset_id, revision)
