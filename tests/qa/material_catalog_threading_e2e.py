#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Installed material-catalog threading/lifecycle replay; no auth or network.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT. Use an idle isolated app.
The INSTALLED server_catalog.py executes under a private package alias with
its own real MaterialRegistry. Only credentials, URL, local-cache loading and
catalog transport are replaced; bpy timers and worker threads are real. The
poll wrapper records results without changing them. No production registry,
auth-store function, user cache or catalog state is patched.

A fake credential lookup waits up to five seconds on an Event. The old
caller-side credential gate fails both the thread assertion and latency
budget. The fixed worker path permits real heartbeat timers, widget queries
and a screenshot while the credential remains blocked. Then tokenless failure,
login-during-load retry, one success and loaded idempotence are exercised.
This validates installed lifecycle code, not HTTP/auth integration or material
catalog UI population. Inspect credential-pending.png alongside details.json.
"""

import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, ensure_scenes_drawer, run_scenario


INSTALL = r'''
import hashlib
import importlib.util
import logging
from pathlib import Path
import sys
import threading
import time
from types import ModuleType, SimpleNamespace
from mixar.modules.paint.procedural_materials import material_registry as real_mr
from mixar.modules.paint.procedural_materials import server_catalog as installed

assert not hasattr(drv, '_catalog_threading_qa'), 'Previous fixture was not cleaned up'
assert hasattr(bpy.types.WindowManager, 'mixar_matgen_status'), 'Wait for paint registration'
prefix = 'mixar.modules.paint._qa_catalog_threading'
assert not any(n == prefix or n.startswith(prefix + '.') for n in sys.modules)
material_id = 'qa_threading_private_material'
assert real_mr.get_material(material_id) is None
f = drv._catalog_threading_qa = SimpleNamespace(
    prefix=prefix, modules=[], token='', release=threading.Event(),
    token_calls=[], network_calls=[], local_calls=[], ensure_calls=[], polls=[],
    workers=[], polls_finished=0, disposed=False, ticks=0, heartbeat=None,
    main_thread=threading.get_ident(), registry=real_mr.MaterialRegistry(),
    real_registry=real_mr.get_registry(), installed=installed,
    material_id=material_id, catalog=None,
)

def token():
    thread = threading.current_thread()
    value = f.token
    record = {'main_thread': threading.get_ident() == f.main_thread,
              'thread': thread.name, 'token_present': bool(value), 'waiting': True}
    f.token_calls.append(record)
    if not record['main_thread']:
        f.workers.append(thread)
    started = time.monotonic()
    record['released'] = f.release.wait(timeout=5)
    record['duration_ms'] = (time.monotonic() - started) * 1000
    record['waiting'] = False
    return value

def local():
    f.local_calls.append({'main_thread': threading.get_ident() == f.main_thread})

def fetch(auth_token, base_url, result_queue):
    f.network_calls.append({'main_thread': threading.get_ident() == f.main_thread,
                            'synthetic_token': auth_token == 'qa-synthetic-token'})
    assert auth_token == 'qa-synthetic-token' and base_url == 'https://catalog.invalid'
    result_queue.put({'ok': True, 'materials': [
        {'material_id': material_id, 'name': 'QA Private Material', 'category': 'metal'},
    ]})

package = ModuleType(prefix)
package.__path__ = []
registry = ModuleType(prefix + '.material_registry')
registry.ProceduralMaterial = real_mr.ProceduralMaterial
registry.register_material = f.registry.register_material
registry._get_auth_token = token
registry._get_base_url = lambda: 'https://catalog.invalid'
registry._load_local_matgen = local
transport = ModuleType(prefix + '.matgen_client')
transport.fetch_catalog_async = fetch
package.material_registry = registry
package.matgen_client = transport
for module in (package, registry, transport):
    sys.modules[module.__name__] = module
    f.modules.append(module.__name__)
source = Path(installed.__file__)
spec = importlib.util.spec_from_file_location(prefix + '.server_catalog', source)
catalog = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = catalog
f.modules.append(spec.name)
spec.loader.exec_module(catalog)
f.catalog = catalog
original_poll = catalog._poll
def poll(queue):
    if f.disposed:
        f.polls_finished += 1
        return None
    ready = not queue.empty()
    before = catalog.catalog_status()
    returned = original_poll(queue)
    if ready:
        f.polls.append({'before': before, 'after': catalog.catalog_status(),
                        'main_thread': threading.get_ident() == f.main_thread})
    if returned is None:
        f.polls_finished += 1
    return returned
catalog._poll = poll
def ensure():
    started = time.monotonic()
    status = catalog.ensure_server_catalog()
    row = {'status': status, 'duration_ms': (time.monotonic() - started) * 1000}
    f.ensure_calls.append(row)
    return row
f.ensure = ensure
def heartbeat():
    f.ticks += 1
    return None if f.disposed else .02
f.heartbeat = heartbeat
bpy.app.timers.register(heartbeat, first_interval=.02)
result = {'installed_source': str(source), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
          'private_registry': f.registry is not f.real_registry}
'''

SNAPSHOT = '''
f = drv._catalog_threading_qa
result = {
    'status': f.catalog.catalog_status(), 'ticks': f.ticks,
    'credentials': list(f.token_calls), 'network': list(f.network_calls),
    'ensure': list(f.ensure_calls), 'polls': list(f.polls),
    'polls_finished': f.polls_finished,
    'materials': [{'id': m.material_id, 'source': getattr(m, 'source', '')}
                  for m in f.registry.get_all_materials()],
}
'''

PREPARE_CLEANUP = '''
f = getattr(drv, '_catalog_threading_qa', None)
if f is not None:
    f.disposed = True
    f.release.set()
    if f.heartbeat is not None and bpy.app.timers.is_registered(f.heartbeat):
        bpy.app.timers.unregister(f.heartbeat)
result = True
'''

FINISH_CLEANUP = '''
import logging
import sys
from mixar.config import logging_config
from mixar.modules.paint.procedural_materials import material_registry as real_mr
f = getattr(drv, '_catalog_threading_qa', None)
result = {'fixture_removed': True, 'production_registry_untouched': True}
if f is not None:
    assert not any(t.is_alive() for t in f.workers), 'Wait for fake credential workers'
    assert f.polls_finished >= len(f.workers), 'Wait for all private catalog poll timers'
    untouched = real_mr.get_registry() is f.real_registry and real_mr.get_material(f.material_id) is None
    result['production_registry_untouched'] = untouched
    for name in reversed(f.modules):
        sys.modules.pop(name, None)
    for name in list(logging.Logger.manager.loggerDict):
        if name == f.prefix or name.startswith(f.prefix + '.'):
            logger = logging.Logger.manager.loggerDict.pop(name)
            logging_config._loggers.pop(name, None)
            if isinstance(logger, logging.Logger):
                for handler in list(logger.handlers):
                    logger.removeHandler(handler)
                    handler.close()
    del drv._catalog_threading_qa
    assert untouched, 'Private fixture must not register a production material'
'''


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/material-catalog-threading'))
    out.mkdir(parents=True, exist_ok=True)
    evidence = {'cases': [], 'backend_turns': 0}

    def save():
        (out / 'details.json').write_text(json.dumps(evidence, indent=2) + '\n')

    def check(name, checks, **details):
        row = {'case': name, 'checks': checks, 'ok': all(checks.values()), **details}
        evidence['cases'].append(row)
        save()
        if not row['ok']:
            raise ScenarioFail(f'{name}: {checks}')
        return row

    qa.cmd('wait_login', timeout=45)
    assert not qa.status()['busy'], 'Use an idle isolated QA app'
    ensure_scenes_drawer(qa)
    try:
        evidence['fixture'] = qa.step('install_private_catalog', qa.eval, INSTALL)
        started = qa.eval('result = drv._catalog_threading_qa.ensure()')
        first = qa.eval(SNAPSHOT)
        check('nonblocking_tokenless_start', {
            'starts_loading': started['status'] == 'loading',
            'ensure_under_100ms': started['duration_ms'] < 100,
            'no_main_thread_credential_read': not any(c['main_thread'] for c in first['credentials']),
        }, ensure=started, state=first)

        qa.wait('len(drv._catalog_threading_qa.token_calls) == 1 and '
                'drv._catalog_threading_qa.token_calls[0]["waiting"]', timeout=3)
        first_ticks = qa.eval('result = drv._catalog_threading_qa.ticks')
        qa.wait(f'drv._catalog_threading_qa.ticks >= {first_ticks + 3}', timeout=2)
        query_started = time.monotonic()
        widgets = qa.find(area_type='VIEW_3D')
        query_ms = (time.monotonic() - query_started) * 1000
        qa.snap(str(out / 'credential-pending.png'))
        pending = qa.eval(SNAPSHOT)
        check('responsive_while_credential_waits', {
            'heartbeat_advanced': pending['ticks'] >= first_ticks + 3,
            'credential_still_blocked': pending['credentials'][0]['waiting'],
            'viewport_widgets_returned': bool(widgets['widgets']),
            'widget_query_under_1s': query_ms < 1000,
        }, widget_query_ms=query_ms, state=pending)

        qa.eval('drv._catalog_threading_qa.release.set()\nresult = True')
        qa.wait("drv._catalog_threading_qa.catalog.catalog_status() == 'failed'", timeout=5)
        failed = qa.eval(SNAPSHOT)
        check('tokenless_failure', {
            'failed': failed['status'] == 'failed',
            'one_credential_read': len(failed['credentials']) == 1,
            'no_network_or_materials': not failed['network'] and not failed['materials'],
            'result_applied_on_main_thread': bool(failed['polls']) and all(p['main_thread'] for p in failed['polls']),
        }, state=failed)

        qa.eval('''
f = drv._catalog_threading_qa
f.release.clear()
f.token = ''
result = f.ensure()
''')
        qa.wait('len(drv._catalog_threading_qa.token_calls) == 2 and '
                'drv._catalog_threading_qa.token_calls[-1]["waiting"]', timeout=3)
        coalesced = qa.eval('''
f = drv._catalog_threading_qa
f.token = 'qa-synthetic-token'
statuses = [f.ensure()['status'] for _ in range(5)]
result = {'statuses': statuses, 'credential_reads': len(f.token_calls)}
''')
        check('login_while_tokenless_fetch_runs', {
            'loading_calls_coalesce': coalesced['statuses'] == ['loading'] * 5,
            'no_additional_credential_read': coalesced['credential_reads'] == 2,
        }, state=coalesced)
        qa.eval('drv._catalog_threading_qa.release.set()\nresult = True')
        qa.wait("drv._catalog_threading_qa.catalog.catalog_status() == 'loaded'", timeout=5)
        loaded = qa.eval(SNAPSHOT)
        check('login_retry_succeeds_once', {
            'loaded': loaded['status'] == 'loaded',
            'exactly_one_retry': len(loaded['credentials']) == 3,
            'one_network_fetch': len(loaded['network']) == 1,
            'credentials_and_network_on_workers': all(not c['main_thread'] for c in loaded['credentials'] + loaded['network']),
            'server_material_registered': loaded['materials'] == [{'id': 'qa_threading_private_material', 'source': 'server'}],
            'all_results_applied_on_main_thread': len(loaded['polls']) == 3 and all(p['main_thread'] for p in loaded['polls']),
        }, state=loaded)
        statuses = qa.eval('result = [drv._catalog_threading_qa.ensure()["status"] for _ in range(5)]')
        final = qa.eval(SNAPSHOT)
        check('loaded_is_idempotent', {
            'stays_loaded': statuses == ['loaded'] * 5,
            'no_extra_credential_or_network_calls': len(final['credentials']) == 3 and len(final['network']) == 1,
            'all_ensure_calls_under_100ms': all(c['duration_ms'] < 100 for c in final['ensure']),
        }, state=final)
        evidence['ok'] = True
    finally:
        qa.eval(PREPARE_CLEANUP)
        qa.wait("not hasattr(drv, '_catalog_threading_qa') or "
                "(not any(t.is_alive() for t in drv._catalog_threading_qa.workers) and "
                "drv._catalog_threading_qa.polls_finished >= len(drv._catalog_threading_qa.workers))", timeout=8)
        evidence['cleanup'] = qa.eval(FINISH_CLEANUP)
        save()
    return evidence


if __name__ == '__main__':
    run_scenario('material_catalog_threading_e2e', run)
