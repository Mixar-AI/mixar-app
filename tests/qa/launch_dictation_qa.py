#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Launch an isolated macOS QA app via LaunchServices for microphone permissions.

QA_HARNESS=/path/to/harness python3 tests/qa/launch_dictation_qa.py
Uses UAT1 in the isolated profile; never modifies the installed config/keychain.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time

root = Path(__file__).resolve().parents[2]
harness = Path(os.environ['QA_HARNESS'])
bundle = Path(os.environ.get('BUILD', root / 'build/Dev/bin/Mixar.app'))
port = int(os.environ.get('QA_PORT', '4783'))
record = os.environ.get('QA_RECORD', '0') == '1'
with socket.socket() as probe:
    if probe.connect_ex(('127.0.0.1', port)) == 0:
        raise SystemExit(f'QA port {port} already in use')
out = Path(os.environ.get('QA_LAUNCH_OUT', '/tmp/mixie-dictation-app-' + time.strftime('%Y%m%d-%H%M%S')))
profile = out / 'profile'
for folder in ('scripts/startup', 'datafiles/mixar', 'config/mixar'):
    (profile / folder).mkdir(parents=True, exist_ok=True)
shutil.copyfile(harness/'qa_boot_startup.py', profile/'scripts/startup/qa_boot.py')
cfg = json.loads(next((bundle/'Contents/Resources').glob('*/config/mixar.json')).read_text())
(profile/'datafiles/mixar/onboarding_seen.json').write_text(json.dumps({'users_seen': [cfg['dev_bypass']['username'].lower()]}))
(profile/'config/mixar/mixar.json').write_text(json.dumps({'backend_url': os.environ.get('QA_BACKEND_URL', 'https://uat1.mixar.app')}))
env = {'MIXAR_QA': '1', 'MIXAR_USER_RESOURCES': str(profile), 'MIXAR_QA_OUT': str(out),
       'MIXAR_QA_PORT': str(port), 'MIXAR_QA_RECORD': '1' if record else '0',
       'MIXAR_OPERATION_HISTORY_DIR': str(out/'ophistory')}
cmd = ['open', '-n', '--stdout', str(out/'app.log'), '--stderr', str(out/'app.log')]
for key, value in env.items():
    cmd += ['--env', key+'='+value]
cmd += [str(bundle), '--args', '-p', '60', '60', '1680', '1050']
if not record:
    cmd += ['--enable-event-simulate']
cmd += ['--python', str(harness/'driver/qa_server.py')]
subprocess.run(cmd, check=True)
print(json.dumps({'port': port, 'out': str(out)}), flush=True)
