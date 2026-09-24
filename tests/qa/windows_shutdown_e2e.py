# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Quit an isolated Windows app with idle or stalled HTTP workers; no credits.

QA_HARNESS must point at mixar-qa-harness. Optional BUILD is the executable,
QA_EXTRA_PYTHONPATH supplies local test dependencies, and QA_SCENARIO_OUT owns
the profile, snapshots, log and verdict. Run with --stalled-api for the fault.
Only this scenario's own process is terminated if normal quit exceeds 8 seconds.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time


def run(stalled):
    root = Path(__file__).resolve().parents[2]
    harness = Path(os.environ['QA_HARNESS'])
    executable = Path(os.environ.get('BUILD', root / 'build/Dev/bin/mixar.exe'))
    out = Path(os.environ.get('QA_SCENARIO_OUT', root / 'outputs/shutdown-qa/replay'))
    out.mkdir(parents=True, exist_ok=True)
    profile = out / 'profile'
    for folder in ('scripts/startup', 'datafiles/mixar', 'config/mixar'):
        (profile / folder).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(harness / 'qa_boot_startup.py', profile / 'scripts/startup/qa_boot.py')
    config = json.loads(next(executable.parent.glob('*/config/mixar.json')).read_text())
    (profile / 'datafiles/mixar/onboarding_seen.json').write_text(json.dumps({
        'users_seen': [config['dev_bypass']['username'].lower()]}))
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    env = dict(os.environ, MIXAR_QA='1', MIXAR_QA_PORT=str(port),
               MIXAR_USER_RESOURCES=str(profile), MIXAR_QA_OUT=str(out),
               MIXAR_OPERATION_HISTORY_DIR=str(out / 'ophistory'), PYTHONUNBUFFERED='1')
    if os.environ.get('QA_EXTRA_PYTHONPATH'):
        env['PYTHONPATH'] = os.environ['QA_EXTRA_PYTHONPATH']
    sys.path.insert(0, str(harness / 'driver'))
    from qa_client import send

    def command(cmd, **args):
        reply = send({'cmd': cmd, 'args': args}, port, 10)
        if not reply.get('ok'):
            raise AssertionError(reply)
        return reply.get('result')

    verdict = {'stalled_api': stalled, 'passed': False}
    with (out / 'app.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([
            str(executable), '--python-use-system-env', '--enable-event-simulate',
            '-p', '60', '60', '1400', '900', '--python', str(harness / 'driver/qa_server.py'),
        ], env=env, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise AssertionError(f'App exited during startup: {process.returncode}')
                try:
                    state = command('status')
                    if state['logged_in'] and state['state'] == 'IDLE':
                        break
                except OSError:
                    pass
                time.sleep(.25)
            else:
                raise AssertionError('App did not reach logged-in IDLE')
            verdict['before'] = state
            command('eval', code='import faulthandler; '
                    'faulthandler.dump_traceback_later(5, repeat=True); result=True')
            if stalled:
                command('eval', code=f'import sys; sys.path.insert(0, {str(Path(__file__).parent)!r}); '
                        'import shutdown_probe; shutdown_probe.install(); result=True')
                deadline = time.monotonic() + 5
                while not command('eval', code='import shutdown_probe; result=shutdown_probe.entered.is_set()'):
                    if time.monotonic() > deadline:
                        raise AssertionError('HTTP worker did not reach stalled local peer')
                    time.sleep(.1)
            command('click', text='File', but_type='Pulldown')
            command('snap', path=str(out / 'quit-menu.png'))
            # Queue the entire click before it can destroy the window. A
            # menu activates its hovered item on RELEASE, following MOUSEMOVE.
            # Geometry comes from the real Quit widget.
            began = time.monotonic()
            command('eval', code="target=drv.find_one(op='WM_OT_quit_blender')\n"
                    "x1,y1,x2,y2=target['rect']\n"
                    "for event,value in [('MOUSEMOVE','NOTHING'),('LEFTMOUSE','PRESS'),('LEFTMOUSE','RELEASE')]:\n"
                    "    target['_win'].event_simulate(type=event, value=value, "
                    "x=int((x1+x2)/2), y=int((y1+y2)/2))\nresult=True")
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                raise AssertionError('Quit exceeded 8 seconds') from None
            verdict['quit_seconds'] = round(time.monotonic() - began, 3)
            verdict['exit_code'] = process.returncode
            assert process.returncode == 0, verdict
            verdict['passed'] = True
        except Exception as exc:
            verdict['error'] = str(exc)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
    (out / 'verdict.json').write_text(json.dumps(verdict, indent=2))
    print(json.dumps(verdict, indent=2))
    return 0 if verdict['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stalled-api', action='store_true')
    sys.exit(run(parser.parse_args().stalled_api))
