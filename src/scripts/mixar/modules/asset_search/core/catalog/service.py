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

from mixar.modules.common.utils.platform_utils import pid_alive

from .store import Catalog, fuse

# The process that spawned the scanner: (Popen, temp folder, monotonic start).
# Only IT reads done.json and cleans up. Every other process sharing the
# catalog (headless agent workers, QA runners) learns about the scan from the
# store's owner record, never from this global.
_job = None
_last_error = ''
SCAN_DEADLINE = 900        # the owner terminates its scanner past this
FOREIGN_SCAN_GRACE = 60    # after which another process may declare it dead
INTERRUPTED = 'Previous scan was interrupted; Refresh to retry'


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


def _mark_interrupted(catalog, message=INTERRUPTED):
    for lib in catalog.libraries():
        if lib['status'] == 'indexing':
            catalog.status(lib['id'], 'partial', message)


def _foreign_scan(catalog):
    """The owner record of a scan another process started, or None.

    A record whose PID is gone, or older than the owner's deadline plus grace
    (a PID can be recycled), is a crashed scan: its claim is released and its
    half-written libraries become ``partial``. A live one is reported as
    indexing and left alone — resetting it would report a healthy scan as
    interrupted and let this process start a duplicate scanner.
    """
    owner = catalog.scan_owner()
    if owner is None:
        return None
    expired = time.time() - float(owner.get('started', 0)) > SCAN_DEADLINE + FOREIGN_SCAN_GRACE
    if not expired and pid_alive(owner.get('pid')):
        return owner
    catalog.release_scan(owner.get('pid'))
    _mark_interrupted(catalog)
    return None


def _finish_own_job():
    """Reap this process's scanner once it exits; True while it still runs."""
    global _job, _last_error
    proc, folder, started = _job
    elapsed = time.monotonic() - started
    if elapsed > SCAN_DEADLINE and proc.poll() is None:
        proc.kill() if elapsed > SCAN_DEADLINE + 5 else proc.terminate()
    if proc.poll() is None:
        return True
    try:
        result = json.loads((Path(folder) / 'done.json').read_text())
    except (OSError, ValueError):
        result = None
    with inventory() as catalog:
        catalog.release_scan(proc.pid)
        if result is None:
            _last_error = 'Library scan stopped; Refresh to retry. Existing assets were preserved.'
            _mark_interrupted(catalog, _last_error)
        else:
            _last_error = '' if result['success'] else 'Some libraries are unavailable; their last index was preserved.'
    shutil.rmtree(folder, ignore_errors=True)
    _job = None
    return False


def status():
    indexing = bool(_job) and _finish_own_job()
    with inventory() as catalog:
        if not indexing:
            indexing = _foreign_scan(catalog) is not None
        if not indexing:
            _mark_interrupted(catalog)
        return {'schema_version': 1, 'indexing': indexing,
                'source_id': catalog.source_id(),
                'libraries': catalog.libraries(), 'message': _last_error}


def refresh():
    global _job, _last_error
    current = status()
    if current['indexing']:
        return current
    with inventory() as catalog:
        libs = catalog.libraries(private=True)
        if not libs:
            return current
        database = catalog.db.execute('PRAGMA database_list').fetchone()[2]
        folder = tempfile.mkdtemp(prefix='mixar_catalog_')
        plan = Path(folder) / 'plan.json'
        plan.write_text(json.dumps({'database': database, 'libraries': libs,
                                   'done': str(Path(folder) / 'done.json')}))
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        spawned = []

        def start():
            with open(Path(folder) / 'worker.log', 'w') as log:
                spawned.append(subprocess.Popen([bpy.app.binary_path, '-b', '--factory-startup',
                    '--disable-autoexec', '--python', str(Path(__file__).with_name('worker.py')),
                    '--', str(plan)], stdout=log, stderr=subprocess.STDOUT, creationflags=flags))
            return spawned[-1].pid
        try:
            # The claim and the spawn share one write transaction, so two
            # processes refreshing at once cannot both start a scanner.
            owner = catalog.claim_scan(start)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise RuntimeError('Could not start library indexing; try Refresh again') from None
        if owner is None:
            shutil.rmtree(folder, ignore_errors=True)
            return status()
        _job = (spawned[-1], folder, time.monotonic())
        _last_error = ''
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
