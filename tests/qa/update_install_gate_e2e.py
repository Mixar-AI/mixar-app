# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Restart & Update's Windows pre-quit gate and result toasts in the running app.

Run against an isolated QA app (any OS) with QA_HARNESS, MIXAR_QA_PORT and
QA_SCENARIO_OUT set; give the app an isolated HOME and a dummy update channel
so the real check stages nothing. Inside the app the Windows check is forced
on and the native process table is replaced by canned rows; the helper spawn
and the quit are stubbed and telemetry is muted, so nothing installs, quits or
reports. Every patch is restored at the end.

1. Restart & Update (the operator) with another Mixar window, a Claude-hosted
   connector and an abandoned connector: the abandoned one is ended, the
   "Close other apps to update" toast names the other two.
2. Only Mixar's own background work: the "Finishing background work" toast
   with Cancel, one poll timer. A real click on Cancel stops it; "Mixar
   Update Ready" returns.
3. Waiting again, then the work ends: the poll continues the update by itself.
4. Planted helper results read at startup: 3010 and locked.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario

SETUP = r"""
import bpy, os, sys, types
from mixar.modules.common.analytics import update_events
from mixar.modules.common.updates.core import (
    app_paths, install_flow, install_gate, installer, result_report, staging, win_processes)
from mixar.modules.common.updates.core.state import UpdateInfo, get_update_state
from mixar.modules.common.notifications.store import get_notification_store

q = types.ModuleType('qa_update_gate')
sys.modules['qa_update_gate'] = q
q.saved = [(install_gate, '_is_windows'), (installer, 'check_eligibility'),
           (installer, 'begin_install'), (win_processes, '_process_table'),
           (win_processes, 'terminate'), (install_flow, '_quit'),
           (install_flow, '_quit_watchdog'), (update_events, 'capture_update_started'),
           (result_report, '_capture_result')]
q.saved = [(owner, name, getattr(owner, name)) for owner, name in q.saved]
q.install_dir = r'C:\Program Files\Mixar'
q.own = os.getpid()
q.table, q.ended, q.began = [], [], []

def row(pid, ppid, name, path, created, window=False):
    return {'pid': pid, 'ppid': ppid, 'name': name, 'path': path,
            'created': created, 'has_window': window}
q.row = row
q.us = row(q.own, 1, 'mixar.exe', q.install_dir + r'\mixar.exe', 10, True)

class Helper:
    pid = 0
    def poll(self): return 0
    def kill(self): pass

def begin_install(**kwargs):
    q.began.append(kwargs.get('signer_thumbprint'))
    return Helper()

def terminate(holder):
    q.ended.append(holder.pid)
    return True

location = app_paths.InstallLocation(q.install_dir, True, '', kind='msi')
install_gate._is_windows = lambda: True
installer.check_eligibility = lambda info: installer.Eligibility(
    True, location=location, extension='.msi')
installer.begin_install = begin_install
win_processes._process_table = lambda: list(q.table)
win_processes.terminate = terminate
install_flow._quit = lambda: None
install_flow._quit_watchdog = lambda: None
update_events.capture_update_started = lambda *a, **k: None
result_report._capture_result = lambda *a, **k: None

q.staging = staging.resolve_staging_dir().path
msi = os.path.join(q.staging, 'Mixar-9.9.9.msi')
open(msi, 'wb').write(b'MIXAR_QA_ONLY')
state = get_update_state()
state.set_available(UpdateInfo(
    latest_version='9.9.9', current_version='4.3.4',
    download_url='https://example.invalid/Mixar-9.9.9.msi',
    download_sha256='a' * 64, installer_type='msi'))
state.set_ready(msi, True, 'AB' * 20)
get_notification_store().clear_all()
result = {'staging': q.staging, 'dirty': bool(bpy.data.is_dirty)}
"""

CLICK = r"""
import bpy, sys
q = sys.modules['qa_update_gate']
window = bpy.context.window_manager.windows[0]
with bpy.context.temp_override(window=window, screen=window.screen):
    ret = bpy.ops.mixar.restart_to_update('EXEC_DEFAULT')
result = sorted(ret)
"""

TOAST = r"""
import bpy, sys
from mixar.modules.common.notifications.store import get_notification_store
from mixar.modules.common.updates.constants import UPDATE_NOTIFICATION_ID
from mixar.modules.common.updates.core import install_gate
from mixar.modules.common.updates.core.state import get_update_state
q = sys.modules['qa_update_gate']
item = next((i for i in get_notification_store().get_visible()
             if i.id == UPDATE_NOTIFICATION_ID), None)
result = {
    'title': item and item.title, 'body': item and item.body,
    'actions': item and [[a.label, a.operator] for a in item.actions],
    'dismissible': item and item.dismissible,
    'polling': bpy.app.timers.is_registered(install_gate._poll),
    'waiting': install_gate.is_waiting(),
    'install_state': get_update_state().install_state.value,
    'ended': list(q.ended), 'began': list(q.began),
}
"""

RESTORE = r"""
import os, sys
from mixar.modules.common.updates.core import install_gate
from mixar.modules.common.updates.core.state import get_update_state
from mixar.modules.common.notifications.store import get_notification_store
q = sys.modules.pop('qa_update_gate', None)
if q is not None:
    for owner, name, value in q.saved:
        setattr(owner, name, value)
    for name in ('Mixar-9.9.9.msi', 'update-result.txt'):
        try:
            os.remove(os.path.join(q.staging, name))
        except OSError:
            pass
install_gate.cancel_wait() if install_gate.is_waiting() else None
get_update_state().set_idle()
get_notification_store().clear_all()
result = True
"""


def _toast(qa):
    return qa.eval(TOAST)


def _table(qa, *rows):
    qa.eval("import sys; q = sys.modules['qa_update_gate']; q.table[:] = [q.us, "
            + ", ".join(f"q.row(*{list(r)!r})" for r in rows) + "]; result = len(q.table)")


def _plant_result(qa, text):
    qa.eval(f"""
import os, sys
from mixar.modules.common.updates.core import toasts
q = sys.modules['qa_update_gate']
open(os.path.join(q.staging, 'update-result.txt'), 'w').write({text!r})
toasts.report_previous_update_result()
result = os.path.exists(os.path.join(q.staging, 'update-result.txt'))
""")


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT']).resolve()
    out.mkdir(parents=True, exist_ok=True)
    mixar, python = r'C:\Program Files\Mixar\mixar.exe', r'C:\Program Files\Mixar\5.2\python\bin\python.exe'
    verdict = {'setup': qa.eval(SETUP)}
    if verdict['setup']['dirty']:
        raise ScenarioFail('the QA file is dirty: Restart & Update would refuse to run')
    try:
        # 1. Programs to close, plus an abandoned connector that is ended.
        own = qa.eval("import os; result = os.getpid()")
        _table(qa, (2001, 1, 'mixar.exe', mixar, 5, True),
               (2100, 1, 'Claude.exe', r'C:\Users\u\AppData\Local\AnthropicClaude\Claude.exe', 3),
               (2101, 2100, 'cmd.exe', r'C:\Windows\System32\cmd.exe', 4),
               (2102, 2101, 'python.exe', python, 4),
               (2200, 99999, 'python.exe', python, 30))
        verdict['close_apps_op'] = qa.eval(CLICK)
        toast = verdict['close_apps'] = _toast(qa)
        if toast['title'] != 'Close other apps to update' or toast['ended'] != [2200]:
            raise ScenarioFail(f'close-apps: {toast}')
        for line in ('Another Mixar window', 'Claude (using the Mixar connector)'):
            if line not in toast['body']:
                raise ScenarioFail(f'close-apps toast lacks {line!r}: {toast}')
        if toast['polling'] or toast['began'] or toast['install_state'] != 'ready':
            raise ScenarioFail(f'close-apps must not wait or install: {toast}')
        qa.snap(str(out / 'update-close-apps.png'))

        # 2. Only our own background work: wait, then Cancel.
        background = [(2300, own, 'mixar.exe', mixar, 20), (2301, 99999, 'mixar.exe', mixar, 40)]
        _table(qa, *background)
        verdict['wait_op'] = qa.eval(CLICK)
        toast = verdict['waiting'] = _toast(qa)
        if toast['title'] != 'Finishing background work' or not toast['polling']:
            raise ScenarioFail(f'background wait: {toast}')
        if toast['actions'] != [['Cancel', 'mixar.cancel_update_wait']] or toast['dismissible']:
            raise ScenarioFail(f'background wait toast: {toast}')
        qa.snap(str(out / 'update-background-wait.png'))
        # A real click on the toast's Cancel; it fires after a 0.12 s press flash.
        qa.click(surface='toast_action', text='Cancel')
        qa.wait("not __import__('mixar.modules.common.updates.core.install_gate', "
                "fromlist=['is_waiting']).is_waiting()", timeout=10)
        toast = verdict['cancelled'] = _toast(qa)
        if toast['title'] != 'Mixar Update Ready' or toast['polling'] or toast['waiting']:
            raise ScenarioFail(f'cancel: {toast}')
        qa.snap(str(out / 'update-wait-cancelled.png'))

        # 3. Wait again; the work ends and the poll continues by itself.
        verdict['rewait_op'] = qa.eval(CLICK)
        _table(qa)
        qa.wait("__import__('sys').modules['qa_update_gate'].began", timeout=15)
        toast = verdict['continued'] = _toast(qa)
        if toast['began'] != ['AB' * 20] or toast['install_state'] != 'installing':
            raise ScenarioFail(f'continue after the wait: {toast}')
        qa.eval("from mixar.modules.common.updates.core.state import get_update_state; "
                "import sys; q = sys.modules['qa_update_gate']; s = get_update_state(); "
                "s.set_ready(s.installer_path, True, 'AB' * 20); result = True")

        # 4. Results the helper left for the next launch.
        _plant_result(qa, 'version=9.9.9\nstage=install\nexit=3010\nhelper_version=3\n')
        toast = verdict['pending_reboot'] = _toast(qa)
        if toast['title'] != 'Restart Windows to finish updating':
            raise ScenarioFail(f'3010 toast: {toast}')
        qa.snap(str(out / 'update-result-3010.png'))
        _plant_result(qa, 'version=9.9.9\nstage=locked\nexit=locked\nhelper_version=3\n'
                          'locks=python.exe,mixar.exe\n')
        toast = verdict['locked'] = _toast(qa)
        if toast['title'] != 'Update was not installed' or 'python.exe, mixar.exe' not in toast['body']:
            raise ScenarioFail(f'locked toast: {toast}')
        qa.snap(str(out / 'update-result-locked.png'))
    finally:
        qa.eval(RESTORE)
    (out / 'update-install-gate-verdict.json').write_text(json.dumps(verdict, indent=2))
    return verdict


if __name__ == '__main__':
    run_scenario('update_install_gate', run)
