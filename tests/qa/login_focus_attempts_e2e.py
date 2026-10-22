#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Browser sign-in: one attempt at a time, and the bubble never steals focus.

Replays the three PR #1847 review blockers in the real app:

1. While a sign-in waits on the browser the login popover shows a status
   line and Cancel, never a clickable "waiting" button. Cancel closes the
   loopback callback server and brings Login with Browser back with no
   error; Sign in from another surface (MCP dialog, F3) replaces a pending
   one silently.
2. While the user is in the "browser" (another app is frontmost) the Agent
   Bubble autoshow is held; a FAILED sign-in does not activate Mixar or open
   the bubble; the bubble appears once the user returns to Mixar, and the popover shows
   the failure instead of a stale waiting state.
3. A SUCCESSFUL sign-in brings Mixar forward (``mixar.activate_app``) and the
   bubble follows.

The browser is stubbed (no real browser tab): ``sso.webbrowser.open`` records
the desktop-login URL and Finder is activated to stand in for the browser
taking focus. The loopback callback server, the attempt registry, the
autoshow gate and ``wm.mixar_app_active`` are real. The failure path posts a
synthetic code to the build's backend (rejected, no account touched); the
success path returns the QA app's own dev-bypass token pair from
``_exchange_code`` (in-memory keyring, OS keychain untouched).

macOS only (lsappinfo/osascript). It moves OS focus between Finder and the
QA app, so run it while not typing elsewhere. Export QA_HARNESS,
MIXAR_QA_PORT and QA_SCENARIO_OUT. No credits.
"""
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/login_focus_attempts'))
OUT.mkdir(parents=True, exist_ok=True)

SETUP = r'''
import types
from mixar.config import config as _cfg
from mixar.modules.auth.core import sso as _sso
if not hasattr(_sso, '_qa_saved'):
    _sso._qa_saved = (_sso.webbrowser, _cfg.get_dev_bypass_credentials, _sso._exchange_code)
_sso._qa_opened = []
_sso.webbrowser = types.SimpleNamespace(open=lambda url, *a, **k: _sso._qa_opened.append(url) or True)
_cfg.get_dev_bypass_credentials = lambda: (None, None)
result = True
'''

TEARDOWN = r'''
from mixar.config import config as _cfg
from mixar.modules.auth.core import sso as _sso
saved = getattr(_sso, '_qa_saved', None)
if saved:
    _sso.webbrowser, _cfg.get_dev_bypass_credentials, _sso._exchange_code = saved
    del _sso._qa_saved
result = True
'''

STATE = r'''
from mixar.modules.auth.core import sso as _sso
from mixar.modules.common.utils import sign_in as _si
from mixar.modules.agent_bubble.core.bubble_lifecycle import has_agent_bubble_windows
wm = bpy.data.window_managers[0]
result = {
    'app_active': getattr(wm, 'mixar_app_active', None),
    'logging_in': bool(wm.mixie_chat_is_logging_in),
    'logged_in': bool(wm.mixie_chat_is_logged_in),
    'login_error': wm.mixie_chat_login_error,
    'pending': _si.sign_in_pending(),
    'attempt_id': _si._attempt_id,
    'holds_autoshow': _si.sign_in_holds_autoshow(),
    'bubble': bool(has_agent_bubble_windows()),
    'opened': list(getattr(_sso, '_qa_opened', [])),
}
'''

# Signed out without the logout operator's side effects (it would drop the
# QA app's dev-bypass pair); the top bar then needs its own redraw.
SIGNED_OUT = r'''
from mixar.modules.common.utils.sign_in import redraw_sign_in_surfaces
wm = bpy.data.window_managers[0]
wm.mixie_chat_is_logged_in = False
redraw_sign_in_surfaces(wm)
result = True
'''

HIDE_BUBBLE_AND_ARM = r'''
from mixar.modules.agent_bubble.core import bubble_lifecycle as _bl
from mixar.modules.agent_bubble.core.bubble_autoshow import arm_autoshow
_bl.close_restored_agent_bubble_windows()
arm_autoshow()
result = True
'''


def _app_pid(qa):
    return qa.eval('import os; result = os.getpid()')


def front_pid():
    asn = subprocess.run(['lsappinfo', 'front'], capture_output=True, text=True).stdout.strip()
    info = subprocess.run(['lsappinfo', 'info', '-only', 'pid', asn],
                          capture_output=True, text=True).stdout
    match = re.search(r'"?pid"?\s*=\s*(\d+)', info)
    if not match:
        raise ScenarioFail(f'cannot read the frontmost app pid from lsappinfo: {info!r}')
    return int(match.group(1))


def activate_finder():
    subprocess.run(['osascript', '-e', 'tell application "Finder" to activate'], check=True)


def activate_pid(pid):
    subprocess.run(['osascript', '-e',
                    'tell application "System Events" to set frontmost of '
                    f'(first process whose unix id is {pid}) to true'], check=True)


def bring_mixar_forward(qa, pid, tries=3):
    """Activate the QA app until its native focus flag agrees. Another app
    (the terminal running this) can take focus back in between: retry."""
    for _ in range(tries):
        activate_pid(pid)
        try:
            qa.wait('bpy.data.window_managers[0].mixar_app_active is True', timeout=4)
            return
        except ScenarioFail:
            continue
    raise ScenarioFail('Mixar never became the active app')


def send_user_away(qa):
    """The browser takes focus (Finder stands in for it)."""
    for _ in range(3):
        activate_finder()
        try:
            qa.wait('bpy.data.window_managers[0].mixar_app_active is False', timeout=4)
            return
        except ScenarioFail:
            continue
    raise ScenarioFail('Mixar never lost focus to the stand-in browser')


def port_open(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.5):
            return True
    except OSError:
        return False


def wait_until(fn, timeout, what):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return
        time.sleep(0.2)
    raise ScenarioFail(f'timed out after {timeout}s: {what}')


def login_url(state, index):
    url = state['opened'][index]
    query = parse_qs(urlparse(url).query)
    return int(query['port'][0]), query['state'][0]


def state(qa):
    return qa.eval(STATE)


def snap(qa, name, target=None, margin=120):
    args = {'path': str(OUT / name)}
    if target:
        args['target'] = target
        args['margin'] = margin
    qa.cmd('snap', **args)
    return str(OUT / name)


ATTEMPT = '__import__("mixar.modules.common.utils.sign_in", fromlist=["x"])._attempt_id'
OPENED = "len(__import__('mixar.modules.auth.core.sso', fromlist=['x'])._qa_opened)"
WAITING_TEXT = 'Continue in your browser'
POPOVER_TITLE = "You're using Mixar as a guest"


def popover(qa):
    """The open login popover's widgets: texts and operator ids."""
    widgets = qa.find(area_type='POPUP')['widgets']
    return {'texts': [w.get('text') for w in widgets],
            'ops': [w.get('op') for w in widgets if w.get('op')]}


def open_login_popover(qa):
    """Top bar Guest -> the profile popover, as a person opens it (the first
    click after an activation is often swallowed: retry)."""
    qa.wait("any(w.get('text') == 'Guest' for w in drv.find(area_type='TOPBAR'))", timeout=10)
    for _ in range(3):
        if POPOVER_TITLE in popover(qa)['texts']:
            return
        qa.click(text='Guest', area_type='TOPBAR')
        try:
            qa.wait(f"any(w.get('text') == {POPOVER_TITLE!r} for w in drv.find(area_type='POPUP'))",
                    timeout=3)
            return
        except ScenarioFail:
            continue
    raise ScenarioFail('the login popover never opened')


def click_in_popover(qa, op, done_expr, what):
    """Click a popover button until ``done_expr`` holds (swallowed clicks)."""
    for _ in range(3):
        open_login_popover(qa)
        qa.click(op=op, area_type='POPUP')
        try:
            qa.wait(done_expr, timeout=3)
            return
        except ScenarioFail:
            continue
    raise ScenarioFail(f'{what}: the click never took effect')


def click_sign_in(qa):
    """Login with Browser in the popover; returns once an attempt started."""
    before = qa.eval(f'result = {ATTEMPT}')
    open_login_popover(qa)
    texts = popover(qa)['texts']
    if 'Sign in to Mixar' not in texts:
        raise ScenarioFail(f'popover does not offer Login with Browser: {texts}')
    click_in_popover(qa, 'MIXIE_CHAT_OT_login', f'{ATTEMPT} > {before}', 'Sign in to Mixar')


def wait_popover(qa, text, timeout=3):
    # Profile actions close their card; reopening reads the latest login state.
    open_login_popover(qa)
    qa.wait(f"any(w.get('text') == {text!r} for w in drv.find(area_type='POPUP'))", timeout=timeout)


def run(qa):
    qa.status()
    pid = _app_pid(qa)
    evidence = {'app_pid': pid, 'snaps': []}
    qa.eval(SETUP)
    bring_mixar_forward(qa, pid)
    qa.press('ESC')  # no popover left over from an earlier run
    qa.eval("bpy.data.window_managers[0].mixie_chat_login_error = ''; result = True")
    try:
        return _run(qa, pid, evidence)
    finally:
        qa.eval(TEARDOWN)
        activate_pid(pid)


def _run(qa, pid, evidence):
    # --- native focus signal -------------------------------------------------
    def app_active_tracks_focus():
        bring_mixar_forward(qa, pid)
        send_user_away(qa)
        bring_mixar_forward(qa, pid)
    qa.step('wm.mixar_app_active follows OS focus', app_active_tracks_focus)

    # --- #1 waiting state: a status line and Cancel ---------------------------
    def sign_in_shows_status_and_cancel():
        qa.eval(SIGNED_OUT)
        open_login_popover(qa)
        evidence['snaps'].append(snap(qa, '01_logged_out.png'))
        click_sign_in(qa)
        qa.wait(f'{OPENED} == 1', timeout=10)
        s = state(qa)
        port, _ = login_url(s, -1)
        wait_until(lambda: port_open(port), 5, f'callback server on :{port}')
        assert s['logging_in'] and s['pending'], s
        wait_popover(qa, WAITING_TEXT)
        pop = popover(qa)
        assert 'MIXIE_CHAT_OT_cancel_login' in pop['ops'], pop
        assert 'MIXIE_CHAT_OT_login' not in pop['ops'], f'a clickable sign-in button while waiting: {pop}'
        assert 'Waiting for browser...' not in pop['texts'], pop
        evidence['snaps'].append(snap(qa, '02_waiting.png'))
        evidence['waiting_port'] = port
    qa.step('Sign in shows a status line and Cancel, no clickable waiting button',
            sign_in_shows_status_and_cancel)

    def cancel_returns_to_login():
        port = evidence['waiting_port']
        click_in_popover(qa, 'MIXIE_CHAT_OT_cancel_login',
                         'not bpy.data.window_managers[0].mixie_chat_is_logging_in', 'Cancel')
        wait_popover(qa, 'Sign in to Mixar')
        wait_until(lambda: not port_open(port), 3, f'cancelled callback server :{port} closes')
        time.sleep(1.5)  # let the cancelled thread's exit run
        s = state(qa)
        assert not s['pending'] and not s['logging_in'], s
        assert s['login_error'] == '', f"Cancel surfaced an error: {s['login_error']!r}"
        pop = popover(qa)
        assert 'Login Failed' not in pop['texts'] and WAITING_TEXT not in pop['texts'], pop
        evidence['snaps'].append(snap(qa, '03_cancelled.png'))
    qa.step('Cancel ends the wait and offers Login with Browser again, no error',
            cancel_returns_to_login)

    def other_surface_supersedes():
        click_sign_in(qa)  # a new pending sign-in from the popover
        qa.wait(f'{OPENED} == 2', timeout=10)
        old, _ = login_url(state(qa), -1)
        wait_until(lambda: port_open(old), 5, f'callback server on :{old}')
        # The MCP connect dialog / F3 run the same operator: it replaces.
        qa.eval("bpy.ops.mixie_chat.login(); result = True")
        qa.wait(f'{OPENED} == 3', timeout=10)
        new, _ = login_url(state(qa), -1)
        t0 = time.monotonic()
        if new != old:
            wait_until(lambda: not port_open(old), 3, f'old callback server :{old} closes')
        evidence['supersede_close_s'] = round(time.monotonic() - t0, 2)
        wait_until(lambda: port_open(new), 5, f'new callback server :{new}')
        time.sleep(1.5)
        s = state(qa)
        assert s['logging_in'] and s['pending'], s
        assert s['login_error'] == '', f"superseded attempt surfaced an error: {s['login_error']!r}"
    qa.step('Sign in from another surface replaces the pending one silently',
            other_surface_supersedes)

    def auto_path_never_supersedes():
        r = qa.eval('from mixar.modules.common.utils import sign_in as _si\n'
                    'result = _si.begin_sign_in(supersede=False) is None')
        assert r is True, 'automatic path reserved a second attempt'
    qa.step('automatic path does not take over a pending sign-in', auto_path_never_supersedes)

    # --- #2 autoshow held while away, failure never activates -----------------
    def autoshow_held_in_browser():
        send_user_away(qa)
        qa.eval(HIDE_BUBBLE_AND_ARM)
        time.sleep(3.0)
        s = state(qa)
        assert not s['bubble'], f'bubble opened over the browser: {s}'
        assert front_pid() != pid, 'Mixar was pulled to the front'
        assert s['holds_autoshow'], s
    qa.step('bubble autoshow held while the user is in the browser', autoshow_held_in_browser)

    def failed_sign_in_stays_out():
        port, st = login_url(state(qa), -1)
        urlopen(f'http://127.0.0.1:{port}/callback?code=qa-invalid-code&state={st}',
                timeout=5).read()
        qa.wait('not bpy.data.window_managers[0].mixie_chat_is_logging_in', timeout=40)
        time.sleep(3.0)
        s = state(qa)
        assert s['login_error'], f'no failure surfaced: {s}'
        assert not s['logged_in'], s
        assert not s['bubble'], f'failed sign-in opened the bubble: {s}'
        assert front_pid() != pid, 'failed sign-in activated Mixar'
        evidence['failure_message'] = s['login_error']
    qa.step('failed sign-in neither activates Mixar nor opens the bubble',
            failed_sign_in_stays_out)

    def back_after_failure():
        bring_mixar_forward(qa, pid)
        qa.wait('__import__("mixar.modules.agent_bubble.core.bubble_lifecycle", '
                'fromlist=["x"]).has_agent_bubble_windows()', timeout=10)
        time.sleep(1.0)
        # Blender does not rebuild an open popover when the sign-in ends while
        # the user is away, so it may still show the waiting state; record it.
        open_login_popover(qa)
        pop = popover(qa)
        evidence['popover_on_return'] = pop['texts']
        evidence['snaps'].append(snap(qa, '04_back_after_failure.png'))
        if WAITING_TEXT in pop['texts']:
            # Its stale Cancel must reveal the failure, never wipe it.
            qa.click(op='MIXIE_CHAT_OT_cancel_login', area_type='POPUP')
        wait_popover(qa, 'Sign in to Mixar')
        pop = popover(qa)
        assert WAITING_TEXT not in pop['texts'], f'still waiting: {pop}'
        assert 'Login Failed' in pop['texts'], f'failure not shown: {pop}'
        assert state(qa)['login_error'] == evidence['failure_message']
        evidence['snaps'].append(snap(qa, '04b_failure_shown.png'))
    qa.step('back in Mixar: bubble appears; the popover shows the failure',
            back_after_failure)

    # --- success brings Mixar forward ----------------------------------------
    def success_activates():
        # A fresh real pair from the build's dev-bypass account: the backend
        # half of a successful exchange, without a browser.
        ok = qa.eval(r"""
from mixar.modules.auth.core import sso as _sso, auth as _auth
user, password = _sso._qa_saved[1]()
login = _auth.login(user, password)
pair = ({'access_token': _auth.get_access_token(), 'refresh_token': _auth.get_refresh_token()}, None)
_sso._exchange_code = lambda code, verifier: pair
result = bool(login.get('success') and pair[0]['access_token'] and pair[0]['refresh_token'])
""")
        if ok is not True:
            raise ScenarioFail('could not mint a dev-bypass token pair for the success path')
        qa.eval(SIGNED_OUT)
        click_sign_in(qa)
        qa.wait(f'{OPENED} == 4', timeout=10)
        port, st = login_url(state(qa), -1)
        wait_until(lambda: port_open(port), 5, f'callback server on :{port}')
        send_user_away(qa)
        qa.eval(HIDE_BUBBLE_AND_ARM)
        time.sleep(2.0)
        assert not state(qa)['bubble'], 'bubble opened over the browser'
        urlopen(f'http://127.0.0.1:{port}/callback?code=qa-code&state={st}', timeout=5).read()
        qa.wait('bpy.data.window_managers[0].mixie_chat_is_logged_in and '
                'not bpy.data.window_managers[0].mixie_chat_is_logging_in', timeout=30)
        wait_until(lambda: front_pid() == pid, 5, 'Mixar activated after success')
        qa.wait('__import__("mixar.modules.agent_bubble.core.bubble_lifecycle", '
                'fromlist=["x"]).has_agent_bubble_windows()', timeout=10)
        time.sleep(1.0)
        s = state(qa)
        assert s['login_error'] == '', s
        evidence['snaps'].append(snap(qa, '05_after_success.png'))
    qa.step('successful sign-in brings Mixar forward and the bubble follows',
            success_activates)
    return evidence


if __name__ == '__main__':
    run_scenario('login_focus_attempts_e2e', run)
