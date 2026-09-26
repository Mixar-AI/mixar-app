#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""The force-update gate judges the RUNNING build's version over the agent WS.

Regression for the 4.0.0 outage: the WebSocket handshake sent the constructor
default addon_version "1.0.0", the backend turned it into X-Client-Version,
and every agent command on the newest build was refused as outdated.

Requires the QA app logged into a LOCAL backend (127.0.0.1:8000) as a
superuser (any loopback port): the scenario raises the release floor above the running build
through PATCH /updates/releases, proves the chat is refused with the update
bubble, restores the floor and proves the chat works again. Two cheap model
turns. QA_HARNESS=... QA_SCENARIO_OUT=/tmp/version-gate-qa \
    python3 tests/qa/client_version_gate_e2e.py
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario

SCENE = 'drv.main_window().scene'
CORE = 'mixar.modules.space_mixie_chat.core'
OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/version-gate-qa'))
PROMPT = 'Reply with exactly the word OK and change nothing in the scene.'
OUTDATED = 'Your Mixar version is outdated'
LATEST_RELEASE = os.environ.get('QA_RELEASE_VERSION')  # default: newest published stable


def show(qa):
    if qa.find(surface='pill_cat')['total']:
        qa.click(surface='pill_cat')
    else:
        qa.open_chat()
    time.sleep(.4)


def snap(qa, name):
    show(qa)
    qa.cmd('snap', path=str(OUT / (name + '.png')),
           target={'prop': 'mixie_chat_input', 'area_type': 'AGENT_BUBBLE'}, margin=1500)


def last_agent_text(qa):
    return qa.eval(f'msgs = [m.text for m in {SCENE}.mixie_chat_messages if m.sender == "AGENT"]\n'
                   'result = msgs[-1] if msgs else ""')


def bump(version, by=1):
    parts = [int(p) for p in version.split('.')]
    parts[0] += by
    return '.'.join(str(p) for p in parts)


class Releases:
    """Superuser edits of the local release floor, through the app's own token."""

    def __init__(self, qa, backend):
        self.backend = backend
        self.token = qa.eval('from mixar.modules.auth.core.auth import get_access_token\n'
                             'result = get_access_token()')
        if not self.token:
            raise ScenarioFail('no access token in the app')

    def _call(self, method, path, body=None):
        req = urllib.request.Request(
            self.backend + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())['data']

    def latest_stable(self):
        rows = self._call('GET', '/api/v1/updates/releases?limit=100')['releases']
        published = [r for r in rows
                     if r.get('channel') == 'stable' and r.get('published_at') and r.get('is_active', True)]
        if not published:
            raise ScenarioFail('no published stable release on the local backend')
        return sorted(published, key=lambda r: r['published_at'])[-1]

    def set_floor(self, version, floor):
        self._call('PATCH', f'/api/v1/updates/releases/{version}', {'min_supported_version': floor})


def chat(qa, name, expect_refusal):
    show(qa)
    before = qa.eval(f'result = len({SCENE}.mixie_chat_messages)')
    qa.chat_send(PROMPT)
    if expect_refusal:
        # A refusal is a one-bubble stream with no run behind it, so the chat
        # state never leaves IDLE: wait for the bubble itself, not the turn.
        qa.wait(f'len({SCENE}.mixie_chat_messages) >= {before} + 2', timeout=30)
    else:
        qa.wait_turn(timeout=180)
    time.sleep(1)
    text = last_agent_text(qa)
    snap(qa, name)
    return text


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.cmd('wait_login', timeout=90)
    qa.wait(f'{SCENE}.mixie_chat_state == "IDLE"', timeout=45)
    backend = qa.eval('from mixar.config.config import get_config\nresult = get_config().get("backend_url")')
    if urllib.parse.urlsplit(backend).hostname not in ('localhost', '127.0.0.1'):
        raise ScenarioFail(f'Expected local backend, got {backend}')

    # 1. The handshake carries the running build's version — the same value
    #    PUT /me/client-version reports — never the old "1.0.0" default.
    runtime = qa.eval('from mixar.modules.common.updates.core.update_checker import get_runtime_version\n'
                      'result = get_runtime_version()')
    handshake = qa.eval(f'from {CORE}.jsonrpc_client import get_jsonrpc_client\n'
                        'result = get_jsonrpc_client()._addon_version')
    if not runtime or handshake != runtime or handshake == '1.0.0':
        raise ScenarioFail(f'handshake addon_version {handshake!r} != runtime {runtime!r}')

    releases = Releases(qa, backend)
    release = releases.latest_stable()
    version, old_floor = release['version'], release.get('min_supported_version')
    try:
        # 2. Floor above the running build → the chat is refused with the
        #    update bubble, so the version judged IS the handshake's.
        releases.set_floor(version, bump(runtime))
        refused = chat(qa, 'refused_above_floor', expect_refusal=True)
        if OUTDATED not in refused:
            raise ScenarioFail(f'floor {bump(runtime)} > {runtime} but chat was not refused: {refused[:120]!r}')
        # 3. Floor at the running build → the same chat goes through.
        releases.set_floor(version, runtime)
        answered = chat(qa, 'answered_at_floor', expect_refusal=False)
        if OUTDATED in answered or not answered.strip():
            raise ScenarioFail(f'floor {runtime} == {runtime} but chat was refused: {answered[:120]!r}')
    finally:
        releases.set_floor(version, old_floor)
    return {'runtime': runtime, 'handshake': handshake, 'release': version,
            'refused': refused[:80], 'answered': answered[:80]}


if __name__ == '__main__':
    run_scenario('client_version_gate', run)
