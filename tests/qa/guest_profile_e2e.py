#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Guest profile and browser sign-in, in an isolated offline QA app.

Export QA_HARNESS, MIXAR_QA_PORT, QA_SCENARIO_OUT. Automatic auth must be
disabled and the QA memory keyring installed. No real account or credits.
The browser-open boundary records URLs; token exchange and /me are synthetic.
Real native clicks, SSO/PKCE loopback callbacks, cancellation, worker threads,
identity application and timers run unchanged. Review the emitted screenshots.
"""
import os
from pathlib import Path
import socket
import sys
import time
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/guest-profile-qa'))
OUT.mkdir(parents=True, exist_ok=True)
WM = 'bpy.context.window_manager'
OPENED = "__import__('mixar.modules.auth.core.sso', fromlist=['x'])._qa_guest.opened"
LOGIN = {'op': 'MIXIE_CHAT_OT_login', 'popup': True}
CANCEL = {'op': 'MIXIE_CHAT_OT_cancel_login', 'popup': True}
SETTINGS = {'op': 'MIXAR_BYOK_OT_open_dialog', 'popup': True}
MCP = {'op': 'MIXAR_OT_connect_ai', 'popup': True}

SETUP = '''
import os, types
from mixar.config import config as cfg
from mixar.modules.auth.core import sso, guest
from mixar.modules.space_mixie_chat.ui.operators import auth_ops as auth
from mixar.modules.common.utils import sign_in
assert os.environ.get('MIXAR_QA') == '1'
assert type(__import__('keyring').get_keyring()).__name__ == 'QAMemoryKeyring'
assert not sign_in.sign_in_pending()
assert not auth.get_access_token(), 'Use a fresh offline instance, not a real login'
from mixar.modules.onboarding.core.persistence import mark_device_seen_onboarding
from mixar.modules.onboarding.core.tour import session as tour
if tour.current():
    tour.current().stop('QA menu validation')
mark_device_seen_onboarding()
wm = bpy.context.window_manager
f = types.SimpleNamespace(opened=[], fail_open=False, activations=0)
f.saved = (sso.webbrowser, sso._exchange_code, cfg.get_dev_bypass_credentials,
           auth.get_user_info, auth._apply_account_hooks, auth._capture_session_started,
           auth.activate_app)
f.usage = {name: getattr(wm, name) for name in (
    'mixar_account_name', 'mixar_usage_plan_name', 'mixar_usage_ready',
    'mixar_usage_credits_remaining')}
f.credits = bpy.context.scene.mixie_chat_credits
f.state = (wm.mixie_chat_is_logged_in, wm.mixie_chat_is_guest,
           bpy.context.scene.mixie_chat_user_id, wm.mixie_chat_login_error,
           wm.mixie_chat_session_expired, bpy.context.preferences.view.ui_scale)
def browser_open(url):
    if f.fail_open:
        raise RuntimeError('QA browser unavailable')
    f.opened.append(url)
    return True
def exchange(code, verifier):
    assert verifier
    if code == 'qa-failure':
        return None, {'success': False, 'message': 'QA sign-in was declined'}
    return {'access_token': 'qa-synthetic-access', 'refresh_token': 'qa-synthetic-refresh'}, None
def activate():
    f.activations += 1
    f.saved[6]()
sso.webbrowser = types.SimpleNamespace(open=browser_open)
sso._exchange_code = exchange
cfg.get_dev_bypass_credentials = lambda: (None, None)
auth.get_user_info = lambda: {'status': 'success', 'data': {
    'email': 'qa.profile@example.invalid', 'name': 'QA Profile', 'is_guest': False}}
auth._apply_account_hooks = lambda *args: None
auth._capture_session_started = lambda *args, **kwargs: None
auth.activate_app = activate
sso._qa_guest = f
wm.mixie_chat_is_logged_in = True
wm.mixie_chat_is_guest = True
wm.mixie_chat_login_error = ''
wm.mixie_chat_session_expired = False
bpy.context.scene.mixie_chat_user_id = 'stale@example.invalid'
wm.mixar_account_name = 'Stale Account'
wm.mixar_usage_plan_name = 'Stale Plan'
wm.mixar_usage_ready = True
wm.mixar_usage_credits_remaining = 8765
guest.mark(True, 'qa@guest.mixar.invalid')
sign_in.redraw_sign_in_surfaces(wm)
result = True
'''

CLEANUP = '''
from mixar.config import config as cfg
from mixar.modules.auth.core import sso, guest
from mixar.modules.space_mixie_chat.ui.operators import auth_ops as auth
from mixar.modules.common.utils import sign_in
sign_in.cancel_sign_in()
f = sso._qa_guest
(sso.webbrowser, sso._exchange_code, cfg.get_dev_bypass_credentials,
 auth.get_user_info, auth._apply_account_hooks, auth._capture_session_started,
 auth.activate_app) = f.saved
wm = bpy.context.window_manager
(wm.mixie_chat_is_logged_in, wm.mixie_chat_is_guest,
 bpy.context.scene.mixie_chat_user_id, wm.mixie_chat_login_error,
 wm.mixie_chat_session_expired, bpy.context.preferences.view.ui_scale) = f.state
auth.clear_credentials()
for name, value in f.usage.items():
    setattr(wm, name, value)
bpy.context.scene.mixie_chat_credits = f.credits
guest.mark(wm.mixie_chat_is_guest, bpy.context.scene.mixie_chat_user_id)
sign_in.sync_pending_flag(wm)
sign_in.redraw_sign_in_surfaces(wm)
del sso._qa_guest
result = True
'''


def close(qa):
    for _ in range(3):
        if not qa.find(popup=True)['total']:
            return
        qa.press('ESC')
    assert not qa.find(popup=True)['total']


def open_profile(qa, label='Guest'):
    close(qa)
    qa.click(text=label, area_type='TOPBAR', but_type='Popover')
    qa.wait("bool(drv.find(op='MIXAR_BYOK_OT_open_dialog', popup=True))", timeout=5)


def snap(qa, name):
    path = str(OUT / (name + '.png'))
    qa.cmd('snap', path=path, target=SETTINGS, margin=600)
    return path


def check_guest(qa):
    widgets = qa.cmd('dump', popup=True, limit=100)['widgets']
    ops = {w.get('op') for w in widgets}
    assert {'MIXAR_BYOK_OT_open_dialog', 'MIXAR_OT_connect_ai', 'WM_OT_url_open'} <= ops
    assert not {'MIXIE_CHAT_OT_logout', 'MIXIE_CHAT_OT_open_dashboard',
                'MIXAR_OT_refer_friend', 'MIXAR_OT_open_billing'} & ops
    texts = [w.get('text', '') for w in widgets]
    assert not any('Stale' in text or 'stale@' in text or 'credits' in text.lower() for text in texts)
    assert {'Docs', 'Report a Bug'} <= set(texts)
    login = next(w for w in widgets if w.get('op') in ('MIXIE_CHAT_OT_login', 'MIXIE_CHAT_OT_cancel_login'))
    settings = next(w for w in widgets if w.get('op') == 'MIXAR_BYOK_OT_open_dialog')
    assert login['rect'][1] > settings['rect'][3], 'Sign in must be above tools'


def start_login(qa):
    open_profile(qa)
    count = qa.eval(f'result=len({OPENED})')
    qa.click(**LOGIN)
    qa.wait(f'len({OPENED}) == {count + 1}', timeout=8)
    qa.wait(f'{WM}.mixie_chat_is_logging_in', timeout=5)
    url = qa.eval(f'result={OPENED}[-1]')
    query = parse_qs(urlparse(url).query)
    assert query['source'] == ['desktop'] and query['code_challenge_method'] == ['S256']
    assert query['code_challenge'][0]
    return int(query['port'][0]), query['state'][0]


def callback(qa, code, port, state):
    with urlopen(f'http://127.0.0.1:{port}/callback?code={code}&state={state}', timeout=5) as response:
        assert response.status == 200
    qa.wait(f'not {WM}.mixie_chat_is_logging_in', timeout=10)


def layout_checks(qa):
    """Native macOS resize fixture; other platforms still run the auth replay."""
    if qa.eval('import sys; result=sys.platform') != 'darwin':
        return []
    close(qa)
    qa.eval(f'import sys; sys.path.insert(0, {str(Path(__file__).parent)!r}); result=True')
    frame = qa.eval("import zen_ui_native as native; result=native.frame('host')")
    scale = qa.eval('result=bpy.context.preferences.view.ui_scale')
    zen = qa.eval("result=drv.main_window().workspace.name == 'Zen Mode'")
    shots = []
    try:
        for mode, width in (('ai', 560), ('pro', 1280)):
            qa.click(op='MIXAR_OT_set_ui_mode_' + mode, area_type='TOPBAR')
            qa.eval(f"import zen_ui_native as native; native.frame('host', size=({width}, {frame[3]})); "
                    "bpy.context.preferences.view.ui_scale=1.25; result=True")
            time.sleep(.8)  # OS resize and scale redraw must settle before measuring
            widgets = qa.cmd('dump', area_type='TOPBAR', limit=100)['widgets']
            pill = next(w for w in widgets if w['type'] == 'Popover' and
                        w.get('mixar_component') == 'legacy_card')
            slider = [w for w in widgets if w.get('op') in (
                'MIXAR_OT_set_ui_mode_ai', 'MIXAR_OT_set_ui_mode_pro')]
            assert pill['rect'][0] >= max(w['rect'][2] for w in slider)
            win_width = qa.eval('result=drv.main_window().width * bpy.context.preferences.system.pixel_size')
            assert pill['rect'][2] <= win_width
            # Avatar-only pills have no caption; their tooltip is the semantic target.
            qa.click(text=pill['tip'], but_type='Popover', area_type='TOPBAR')
            qa.wait("bool(drv.find(op='MIXAR_BYOK_OT_open_dialog', popup=True))", timeout=5)
            check_guest(qa)
            shots.append(snap(qa, f'{mode}-{width}-125'))
            close(qa)
    finally:
        close(qa)
        qa.eval(f"import zen_ui_native as native; native.frame('host', size={frame[2:]!r}); "
                f"bpy.context.preferences.view.ui_scale={scale}; result=True")
        qa.click(op='MIXAR_OT_set_ui_mode_' + ('ai' if zen else 'pro'), area_type='TOPBAR')
    return shots


def run(qa):
    close(qa)
    qa.step('install_offline_service_fixture', qa.eval, SETUP)
    shots = []
    try:
        qa.step('open_guest', open_profile, qa)
        qa.step('guest_tools_and_no_stale_account_values', check_guest, qa)
        shots.append(snap(qa, 'guest'))
        shots.extend(qa.step('narrow_zen_and_engine_at_125_percent', layout_checks, qa))
        open_profile(qa)
        qa.step('provider_dialog', qa.click, **SETTINGS)
        qa.wait("bool(drv.find(prop='byok_form_provider', popup=True))", timeout=5)
        assert not qa.find(**MCP)['total'], 'Profile must close when opening a dialog'
        close(qa)
        open_profile(qa)
        qa.step('mcp_dialog', qa.click, **MCP)
        qa.wait("bool(drv.find(op='MIXAR_OT_set_mcp_enabled', popup=True))", timeout=5)
        close(qa)
        port, state = qa.step('start_browser_sign_in', start_login, qa)
        open_profile(qa)
        check_guest(qa)
        assert qa.find(text='Continue in your browser', popup=True)['total']
        assert not qa.find(**LOGIN)['total']
        shots.append(snap(qa, 'waiting'))
        # Reopening and closing the menu never opens another browser tab.
        open_profile(qa)
        assert qa.eval(f'result=len({OPENED})') == 1
        qa.step('cancel_browser_wait', qa.click, **CANCEL)
        qa.wait(f'not {WM}.mixie_chat_is_logging_in', timeout=5)
        time.sleep(1.3)  # cancelled worker has up to one second to close its listener
        with socket.socket() as sock:
            assert sock.connect_ex(('127.0.0.1', port)) != 0
        assert qa.eval(f'result={WM}.mixie_chat_login_error') == ''
        open_profile(qa)
        assert qa.find(**LOGIN)['total'] == 1
        shots.append(snap(qa, 'cancelled'))
        port, state = qa.step('retry_browser_sign_in', start_login, qa)
        qa.step('failed_callback', callback, qa, 'qa-failure', port, state)
        open_profile(qa)
        assert qa.find(text='Login Failed', popup=True)['total']
        assert qa.find(**LOGIN)['total'] == 1
        assert qa.eval("result=__import__('mixar.modules.auth.core.sso',fromlist=['x'])._qa_guest.activations") == 0
        shots.append(snap(qa, 'failure'))
        # A failed browser launch must also release the pending UI immediately.
        qa.eval("__import__('mixar.modules.auth.core.sso',fromlist=['x'])._qa_guest.fail_open=True; result=True")
        qa.click(**LOGIN)
        qa.wait(f"'QA browser unavailable' in {WM}.mixie_chat_login_error", timeout=5)
        assert not qa.eval(f'result={WM}.mixie_chat_is_logging_in')
        qa.eval("__import__('mixar.modules.auth.core.sso',fromlist=['x'])._qa_guest.fail_open=False; result=True")
        port, state = qa.step('retry_after_launch_failure', start_login, qa)
        qa.step('successful_callback', callback, qa, 'qa-success', port, state)
        qa.wait(f'not {WM}.mixie_chat_is_guest and {WM}.mixie_chat_is_logged_in', timeout=5)
        assert qa.eval("result=__import__('mixar.modules.auth.core.sso',fromlist=['x'])._qa_guest.activations") == 1
        open_profile(qa, 'qa.profile@example.invalid')
        assert qa.find(op='MIXIE_CHAT_OT_logout', popup=True)['total'] == 1
        assert qa.find(op='MIXIE_CHAT_OT_open_dashboard', popup=True)['total'] == 1
        assert not qa.find(**LOGIN)['total']
        shots.append(snap(qa, 'signed-in'))
        close(qa)
        qa.eval(f"{WM}.mixie_chat_is_logged_in=False; {WM}.mixie_chat_is_guest=False; "
                f"{WM}.mixie_chat_session_expired=True; "
                "__import__('mixar.modules.common.utils.sign_in',fromlist=['x']).redraw_sign_in_surfaces(bpy.context.window_manager); result=True")
        open_profile(qa)
        check_guest(qa)
        assert qa.find(text='Session expired', popup=True)['total']
        shots.append(snap(qa, 'expired'))
        return {'screenshots': shots, 'browser_handoff': 'recorded; real PKCE and loopback callback',
                'token_exchange': 'synthetic, in-memory keyring', 'credits_spent': 0}
    finally:
        close(qa)
        qa.step('restore_fixture', qa.eval, CLEANUP)


if __name__ == '__main__':
    run_scenario('guest_profile_e2e', run)
