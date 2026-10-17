# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run local, no-credit desktop scenarios in fresh isolated Linux profiles.

QA_HARNESS=/path/to/mixar-qa-harness WAYLAND_DISPLAY= python3 tests/qa/linux_desktop_e2e.py
Optional positional arguments select scenario filenames without the .py suffix.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo / 'tests/qa/sticky_ui'))
from qa_launch import start

harness = Path(os.environ['QA_HARNESS']).resolve()
root = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/mixar-linux-desktop-e2e'))
root.mkdir(parents=True, exist_ok=True)
scenarios = sys.argv[1:] or ['header_adaptive_e2e', 'library_responsive_e2e',
                            'context_folder_attach_ui_e2e', 'zen_scene_toolbar_e2e']
results = []
for index, name in enumerate(scenarios):
    port = 4800 + index
    app = start(harness, repo / 'build/Dev/bin', port, root / name)
    try:
        env = dict(os.environ, MIXAR_QA_PORT=str(port), QA_SCENARIO_OUT=str(app.out))
        with (app.out / 'scenario.log').open('w') as log:
            try:
                code = subprocess.run([sys.executable, str(repo / 'tests/qa' / (name + '.py'))],
                                      env=env, stdout=log, stderr=subprocess.STDOUT,
                                      timeout=300).returncode
            except subprocess.TimeoutExpired:
                code = 'timeout'
        results.append({'scenario': name, 'exit_code': code, 'out': str(app.out)})
        (root / 'verdict.json').write_text(json.dumps(results, indent=2) + '\n')
        print(json.dumps(results[-1]), flush=True)
    finally:
        app.stop(harness)
sys.exit(any(item['exit_code'] != 0 for item in results))
