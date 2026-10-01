#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""BYOK / AI Provider Settings over HTTP: cold start, socket down, disk, logout.

Spends no credits and never opens the dialog before the boot check (its invoke
warms the catalog and would mask a cold-start bug). Six checks, none of which
assume the QA account has a credential stored:

1. The mirror startup left behind agrees with an authoritative refetch.
2. Settings still work with the agent socket DOWN (impossible on the old
   WebSocket transport, which is why they moved to HTTP).
3. The catalog is persisted under the isolated profile's datafiles, never
   `~/.mixar`, and comes back from disk alone after a memory wipe.
4. A FAILED fetch leaves the mirror alone.
5. Logout invalidation (`auth_hooks.invalidate_agent_settings`) empties the
   mirror, the catalog and the disk file; the login refresh restores all three.
6. Vision: the AI Provider Settings dialog renders with populated dropdowns.

QA_HARNESS=/path/to/mixar-qa-harness QA_SCENARIO_OUT=/tmp/byok-qa \
    python3 tests/qa/byok_http_e2e.py
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA, ScenarioFail, run_scenario  # noqa: E402

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/byok-qa'))
WM = 'bpy.data.window_managers[0]'

MIRROR_FIELDS = (
    'byok_is_active',
    'byok_current_provider',
    'byok_current_model',
    'byok_current_supports_vision',
    'byok_key_preview',
)
DEFAULTS = {
    'byok_is_active': False,
    'byok_current_provider': '',
    'byok_current_model': '',
    'byok_current_supports_vision': True,
    'byok_key_preview': '',
}

READ_MIRROR = f"""
from mixar.modules.byok.core import credential_state, model_suggestions
result = credential_state.snapshot()
result['wm'] = {{f: getattr({WM}, f) for f in {MIRROR_FIELDS!r}}}
result['catalog_loaded'] = model_suggestions.is_loaded()
result['providers'] = [p[0] for p in model_suggestions.get_provider_items()]
"""
CATALOG_READY = "__import__('mixar.modules.byok.core.model_suggestions', fromlist=['x']).is_loaded()"
CATALOG_EMPTY = "not " + CATALOG_READY

# Sentinel the fetch callback must overwrite, so each wait is an edge.
PROBE = '__qa_probe__'
ARM_FETCH = f"""
from mixar.modules.byok.core import credential_state
credential_state._state['byok_current_provider'] = {PROBE!r}
credential_state.refresh()
result = True
"""
PROBE_CLEARED = ("__import__('mixar.modules.byok.core.credential_state', fromlist=['x'])"
                 f".snapshot()['byok_current_provider'] != {PROBE!r}")

DISK = """
import os, json, bpy
from mixar.modules.byok.core import models_storage
path = models_storage._disk_path()
stored = json.load(open(path)) if os.path.isfile(path) else None
result = {
    'path': path,
    'datafiles': bpy.utils.user_resource('DATAFILES', path='mixar'),
    'exists': os.path.isfile(path),
    'providers': [p.get('id') for p in ((stored or {}).get('data') or {}).get('providers', [])],
}
"""
DISK_EXISTS = ("__import__('os').path.isfile(__import__('mixar.modules.byok.core.models_storage',"
               " fromlist=['x'])._disk_path())")

KILL_SOCKET = """
from mixar.modules.space_mixie_chat.core.connection_manager import get_connection_manager
from mixar.modules.space_mixie_chat.core.jsonrpc_client import get_jsonrpc_client
get_connection_manager().disconnect()
client = get_jsonrpc_client()
result = {'connected': bool(client and client.is_connected)}
"""
RECONNECT = """
from mixar.modules.space_mixie_chat.core.connection_manager import get_connection_manager
m = get_connection_manager(); m.initialize(); result = m.connect()
"""
WIPE_MEMORY = """
from mixar.modules.byok.core import model_suggestions
model_suggestions.clear()
result = model_suggestions.is_loaded()
"""
RESTORE_FROM_DISK = """
from mixar.modules.byok.core import models_cache, model_suggestions
result = {'loaded_from_disk': models_cache.load_from_disk(),
          'providers': [p[0] for p in model_suggestions.get_provider_items()]}
"""
FAIL_A_FETCH = """
from mixar.modules.byok.ui.operators import byok_state_ops
byok_state_ops._on_fetch_done(False, None, 'Connection timed out. (NET-TIMEOUT)')
result = True
"""
# The real logout / login hooks, minus the token flip.
LOGOUT = """
from mixar.modules.auth.core import auth_hooks
auth_hooks.invalidate_agent_settings()
result = True
"""
LOGIN = """
from mixar.modules.auth.core import auth_hooks
auth_hooks.refresh_agent_settings()
result = True
"""
OPEN_DIALOG = """
import bpy
try:
    result = str(bpy.ops.mixar_byok.open_dialog('INVOKE_DEFAULT'))
except Exception as exc:
    result = 'ERROR: %s' % exc
"""


def diff(left, right, left_name, right_name):
    return {f: {left_name: left.get(f), right_name: right.get(f)}
            for f in MIRROR_FIELDS if left.get(f) != right.get(f)}


def settle_boot_mirror(qa, timeout=25.0):
    """Read the mirror startup left behind, once its own fetch has landed.

    The credential GET and the catalog GET are separate requests, so the
    catalog being ready says nothing about the credential fetch. There is no
    "fetched once" flag to wait on, and an account with no credential settles
    on the defaults, so poll for an edge away from the defaults and accept the
    defaults only after ``timeout`` — the authoritative refetch below then
    decides whether that was right.
    """
    deadline = time.monotonic() + timeout
    while True:
        boot = qa.eval(READ_MIRROR)
        if diff(boot, DEFAULTS, 'boot', 'defaults') or time.monotonic() >= deadline:
            return boot
        time.sleep(0.5)


def run(qa: QA):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.step('wait_login', qa.cmd, 'wait_login', timeout=90)

    # --- 1. startup state agrees with the server ---------------------------
    qa.step('startup_loaded_catalog', qa.wait, CATALOG_READY, timeout=45)
    boot = qa.step('read_boot_mirror', settle_boot_mirror, qa)
    if diff(boot, boot['wm'], 'dict', 'wm'):
        raise ScenarioFail(f"WindowManager mirror disagrees with the state dict: {boot}")
    qa.step('arm_authoritative_fetch', qa.eval, ARM_FETCH)
    qa.step('await_authoritative_fetch', qa.wait, PROBE_CLEARED, timeout=30)
    server = qa.step('read_authoritative_mirror', qa.eval, READ_MIRROR)
    drift = diff(boot, server, 'at_boot', 'authoritative')
    if drift:
        raise ScenarioFail(f"the BYOK mirror left by startup disagrees with the server: {drift}")
    if not server['providers']:
        raise ScenarioFail('the catalog is empty — the dropdowns would render blank')

    # --- 2. settings work with the agent socket down -----------------------
    socket = qa.step('kill_agent_socket', qa.eval, KILL_SOCKET)
    if socket.get('connected'):
        raise ScenarioFail('agent socket did not go down; the check below is void')
    qa.step('arm_fetch_with_socket_down', qa.eval, ARM_FETCH)
    qa.step('await_fetch_with_socket_down', qa.wait, PROBE_CLEARED, timeout=30)
    offline = qa.step('read_mirror_with_socket_down', qa.eval, READ_MIRROR)
    drift = diff(server, offline, 'authoritative', 'socket_down')
    if drift:
        raise ScenarioFail(f"BYOK state changed when the agent socket went down: {drift}")

    # --- 3. the disk cache lives in the profile and restores alone ---------
    qa.step('await_disk_cache', qa.wait, DISK_EXISTS, timeout=30)
    disk = qa.step('read_disk_cache', qa.eval, DISK)
    if not disk['path'].startswith(disk['datafiles']):
        raise ScenarioFail(f"catalog persisted outside the profile datafiles: {disk}")
    # The file holds the raw server payload; the live list adds the client-side
    # providers (OpenRouter, Codex, Local) on top of it.
    if not disk['providers'] or not set(disk['providers']) <= set(server['providers']):
        raise ScenarioFail(f"disk cache disagrees with the live catalog: {disk['providers']} vs {server['providers']}")
    if qa.step('wipe_catalog_memory', qa.eval, WIPE_MEMORY):
        raise ScenarioFail('catalog wipe did not take')
    restored = qa.step('restore_catalog_from_disk', qa.eval, RESTORE_FROM_DISK)
    if not restored['loaded_from_disk'] or restored['providers'] != server['providers']:
        raise ScenarioFail(f"the catalog did not come back from disk intact: {restored}")

    # --- 4. a failed fetch is non-destructive ------------------------------
    qa.step('simulate_failed_fetch', qa.eval, FAIL_A_FETCH)
    post = qa.step('read_mirror_after_failure', qa.eval, READ_MIRROR)
    drift = diff(server, post, 'before_failure', 'after_failure')
    if drift:
        raise ScenarioFail(f"a FAILED fetch wiped cached BYOK state: {drift}")

    # --- 5. logout empties everything; login restores everything -----------
    qa.step('logout_invalidation', qa.eval, LOGOUT)
    qa.step('await_catalog_cleared', qa.wait, CATALOG_EMPTY, timeout=10)
    cleared = qa.step('read_mirror_after_logout', qa.eval, READ_MIRROR)
    if diff(cleared, DEFAULTS, 'after_logout', 'defaults') or diff(cleared['wm'], DEFAULTS, 'wm', 'defaults'):
        raise ScenarioFail(f"logout left BYOK state behind for the next account: {cleared}")
    gone = qa.step('read_disk_after_logout', qa.eval, DISK)
    if gone['exists']:
        raise ScenarioFail(f"logout left the previous account's catalog on disk: {gone['path']}")
    qa.step('login_refresh', qa.eval, LOGIN)
    qa.step('await_catalog_after_login', qa.wait, CATALOG_READY, timeout=30)
    qa.step('await_disk_after_login', qa.wait, DISK_EXISTS, timeout=30)
    qa.step('await_mirror_after_login', qa.wait,
            "__import__('mixar.modules.byok.core.credential_state', fromlist=['x']).snapshot()"
            f" == {dict((f, server[f]) for f in MIRROR_FIELDS)!r}", timeout=30)
    relogin = qa.step('read_mirror_after_login', qa.eval, READ_MIRROR)
    if relogin['providers'] != server['providers'] or diff(relogin['wm'], server, 'wm', 'authoritative'):
        raise ScenarioFail(f"login did not restore the settings: {relogin}")

    qa.step('reconnect_agent_socket', qa.eval, RECONNECT)

    # --- 6. vision --------------------------------------------------------
    opened = qa.step('open_settings_dialog', qa.eval, OPEN_DIALOG)
    time.sleep(1.0)
    shot = str(OUT / 'byok_http_e2e.png')
    qa.step('snap', qa.snap, shot)
    return {
        'at_boot': {f: boot[f] for f in MIRROR_FIELDS},
        'byok_configured': bool(server['byok_is_active']),
        'providers': server['providers'],
        'disk_path': disk['path'],
        'survives_socket_down': True,
        'catalog_restored_from_disk': True,
        'survives_failed_fetch': True,
        'logout_clears_and_login_restores': True,
        'dialog_opened': opened,
        'snap': shot,
    }


if __name__ == '__main__':
    run_scenario('byok_http_e2e', run)
