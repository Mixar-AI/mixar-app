# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Validate Windows update helper results and the real cancellation toast.

Run against an isolated Windows QA app with QA_HARNESS, MIXAR_QA_PORT and
QA_SCENARIO_OUT set. Only the elevated installer is substituted by an argv
recorder or Win32 cancellation. No MSI is run; no app quit or restart occurs.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT']).resolve()
    out.mkdir(parents=True, exist_ok=True)
    code = f"""
import os, sys, threading
assert os.environ.get('MIXAR_QA') == '1'
sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})
import windows_update_probe as probe
from mixar.modules.common.updates.core import win_installer
probe.results = []
probe.error = None
def work():
    try:
        for cancelled, label in [(False, 'spaces'), (True, 'cancel')]:
            probe.results.append(probe.run_batch_case(
                win_installer, os.path.join({str(out)!r}, label),
                {sys.executable!r}, cancelled=cancelled))
    except Exception as exc:
        probe.error = str(exc)
probe.worker = threading.Thread(target=work, daemon=True)
probe.worker.start()
result=True
"""
    qa.eval(code)
    qa.wait("not __import__('windows_update_probe').worker.is_alive()", timeout=45)
    result = qa.eval('import windows_update_probe as p; result={"cases":p.results,"error":p.error}')
    assert result['error'] is None, result
    assert len(result['cases']) == 2, result
    # Feed the actual generated result file through the existing startup
    # reader and renderer. Restore the staging lookup immediately afterwards.
    cancelled_dir = result['cases'][1]['staging_dir']
    toast = qa.eval(f"""
from mixar.modules.common.updates.core import install_flow, installer, toasts
from mixar.modules.common.notifications.store import get_notification_store
from mixar.modules.common.updates.constants import UPDATE_NOTIFICATION_ID
saved_read = install_flow.read_previous_result
saved_capture = toasts._capture_result
try:
    install_flow.read_previous_result = lambda: installer.consume_result({cancelled_dir!r})
    toasts._capture_result = lambda *args: None
    toasts.report_previous_update_result()
finally:
    install_flow.read_previous_result = saved_read
    toasts._capture_result = saved_capture
item=next(i for i in get_notification_store().get_visible() if i.id == UPDATE_NOTIFICATION_ID)
result={{'title':item.title,'body':item.body,'actions':[a.label for a in item.actions]}}
""")
    assert toast['title'] == 'Update was not installed', toast
    assert 'cancelled' in toast['body'], toast
    assert toast['actions'] == ['Download'], toast
    qa.snap(str(out / 'cancelled-update.png'))
    assert not (Path(cancelled_dir) / 'update-result.txt').exists()
    result['toast'] = toast
    (out / 'verdict.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    run_scenario('windows_update_helper', run)
