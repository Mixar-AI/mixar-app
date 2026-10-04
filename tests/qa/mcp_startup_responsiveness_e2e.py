#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Launch an isolated real app with a locked MCP receipt database.

Usage: python3 tests/qa/mcp_startup_responsiveness_e2e.py --app /path/to/Mixar
       --harness /path/to/mixar-qa-harness --out /tmp/mixar-startup-qa

The output directory must be new. Uses no paid agent calls. Proves deferred
registration and native menu input work during a real SQLite lock, then checks
normal-loop responsiveness and receipt recovery. Review the saved screenshots.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import time


MEASURE = '''
import time
from mixar.modules.common.ui_control.core import service
def measure():
    assert not bpy.app.use_event_simulate
    start = previous = time.perf_counter()
    intervals = []
    while time.perf_counter() - start < 3:
        yield .02
        now = time.perf_counter()
        intervals.append(now - previous)
        previous = now
        assert not service._registered, "Locked journal must not admit UI actions"
    intervals.sort()
    return dict(samples=len(intervals), p95_ms=1000*intervals[int(.95*len(intervals))],
                max_ms=1000*max(intervals), receipt_state=service.receipt_startup_status())
result=measure()
'''


def launch(args, out):
    profile = out / 'profile'
    for leaf in ('scripts/startup', 'config/mixar/ui-control', 'datafiles/mixar'):
        (profile / leaf).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.harness / 'qa_boot_startup.py', profile / 'scripts/startup/qa_boot.py')
    (profile / 'scripts/startup/qa_seen.py').write_text('''
import json
from pathlib import Path
import bpy
from mixar.config.config import get_config
username = get_config().get('dev_bypass', {}).get('username', '').strip().lower()
path = Path(bpy.utils.user_resource('DATAFILES')) / 'mixar/onboarding_seen.json'
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps({'users_seen': [username]}))
def register(): pass
def unregister(): pass
''')
    (profile / 'config/mixar/mixar.json').write_text(json.dumps({'mcp_enabled': True}))
    path = profile / 'config/mixar/ui-control/receipts.sqlite'
    # Hold a writer in another process from before app launch. The initializer
    # must wait/fail without occupying Blender's main thread.
    blocker = sqlite3.connect(path)
    blocker.execute('PRAGMA journal_mode=WAL')
    blocker.execute('CREATE TABLE qa_lock (value INTEGER)')
    blocker.commit()
    blocker.execute('BEGIN IMMEDIATE')
    env = dict(os.environ, MIXAR_QA='1', MIXAR_USER_RESOURCES=str(profile),
               MIXAR_QA_OUT=str(out), MIXAR_QA_PORT=str(args.port), MIXAR_QA_RECORD='0',
               MIXAR_MCP_DISCOVERY_DIR=str(out / 'mcp'),
               MIXAR_AGENT_HISTORY_DIR=str(out / 'agent-history'),
               MIXAR_OPERATION_HISTORY_DIR=str(out / 'operation-history'))
    with (out / 'app.log').open('w') as log:
        app = subprocess.Popen([str(args.app), '-p', '60', '60', '1440', '900',
                                '--enable-event-simulate', '--python',
                                str(args.harness / 'driver/qa_server.py')],
                               env=env, stdout=log, stderr=subprocess.STDOUT)
    return app, blocker


def run(args):
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(args.harness / 'scenarios'))
    from lib import QA
    qa = QA(args.port)
    app, blocker = launch(args, out)
    facts = {}
    started = time.monotonic()
    try:
        deadline = started + 60
        while True:
            if app.poll() is not None:
                raise RuntimeError('QA app exited; inspect app.log')
            try:
                with socket.create_connection(('127.0.0.1', args.port), timeout=.5):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError('QA app did not start')
                time.sleep(.2)
        qa.step('deferred-ui-completes-with-locked-db', qa.wait,
                "__import__('bootstrap')._ui_loading_complete", timeout=20)
        facts['startup_seconds'] = time.monotonic() - started
        # Wait for the scheduled connector attempt (three seconds after launch).
        qa.wait("__import__('mixar.modules.common.ui_control.core.service', "
                "fromlist=['x']).receipt_startup_status()['state'] in {'starting', 'retrying'}", timeout=10)
        facts['locked'] = qa.eval('''import bootstrap
from mixar.modules.common.ui_control.core import service
from mixar.modules.mcp_bridge.core import runtime
assert runtime.enabled() and not service._registered
assert runtime.is_running(), "Receipt failure must not prevent relay startup"
result=dict(complete=bootstrap._ui_loading_complete, modules=len(bootstrap._loaded_ui_modules),
            receipt_state=service.receipt_startup_status())
''')
        qa.step('open-native-help-during-db-lock', qa.click, text='Help', but_type='Pulldown')
        qa.wait("bool(drv.find(op='MIXAR_OT_connect_ai', popup=True))", timeout=5)
        # The target exists before the frame that paints it reaches the window.
        qa.eval('def settle():\n    yield .5\n    return True\nresult=settle()')
        qa.snap(str(out / 'menu-during-db-lock.png'))
        qa.press('ESC')
        qa.step('switch-native-workspace-during-db-lock', qa.click, op='MIXAR_OT_set_ui_mode_pro')
        qa.wait("__import__('mixar.config.config', fromlist=['x']).get_ui_mode() == 'pro'", timeout=5)
        qa.eval('def settle():\n    yield .5\n    return True\nresult=settle()')
        qa.snap(str(out / 'engine-during-db-lock.png'))
        qa.click(op='MIXAR_OT_set_ui_mode_ai')
        qa.wait("__import__('mixar.config.config', fromlist=['x']).get_ui_mode() == 'ai'", timeout=5)
        qa.eval('bpy.app.use_event_simulate=False\nresult=True')
        facts['responsive_while_locked'] = qa.step('normal-event-loop-during-db-lock', qa.eval, MEASURE)
        assert facts['responsive_while_locked']['samples'] > 50, facts
        assert facts['responsive_while_locked']['max_ms'] < 500, facts
        blocker.rollback()
        blocker.close()
        blocker = None
        qa.step('receipt-initialization-recovers', qa.wait,
                "__import__('mixar.modules.common.ui_control.core.service', fromlist=['x'])._registered",
                timeout=70)
        facts['recovered'] = qa.eval('''from uuid import uuid4
from mixar.modules.common.ui_control.core import service
call = str(uuid4())
journal = service._receipts
digest = journal.digest('qa-startup', 'qa-receipt', {})
journal.claim(call, digest)
journal.finish(call, 'succeeded')
assert journal.prior(call, digest)['status'] == 'succeeded'
result=dict(receipt=journal.status(call), startup=service.receipt_startup_status())
''')
        qa.snap(str(out / 'recovered-viewport.png'))
        facts['passed'] = True
        return facts
    except Exception as exc:
        facts.update(passed=False, error=str(exc))
        raise
    finally:
        (out / 'verdict.json').write_text(json.dumps(dict(facts, steps=qa.log), indent=2))
        if blocker is not None:
            blocker.rollback()
            blocker.close()
        if app.poll() is None:
            try:
                qa.eval('bpy.ops.wm.quit_blender()')
            except Exception:
                pass
            try:
                app.wait(timeout=8)
            except subprocess.TimeoutExpired:
                app.terminate()
                app.wait(timeout=8)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', required=True, type=Path)
    parser.add_argument('--harness', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--port', type=int, default=4838)
    print(json.dumps(run(parser.parse_args()), indent=2))
