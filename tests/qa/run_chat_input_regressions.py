#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Run the no-credit chat/native-input regression suite on an isolated QA app.

Set QA_HARNESS, MIXAR_QA_PORT and optionally QA_SCENARIO_OUT before running.
Each scenario prepares its own state; fail at the first regression.
"""
import os
from pathlib import Path
import subprocess
import sys

SCENARIOS = (
    'blender_native_text_fields_e2e.py',
    'chat_popup_enter_activation_e2e.py',
    'mixie_caret_placement_e2e.py',
    'multiline_field_isolation_e2e.py',
    'mixie_text_selection_e2e.py',
    'mixie_open_type_send_e2e.py',
    'voice_composer_focus_e2e.py',
)

if __name__ == '__main__':
    root = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/chat-input-regressions'))
    for scenario in SCENARIOS:
        env = dict(os.environ, QA_SCENARIO_OUT=str(root / Path(scenario).stem))
        subprocess.run([sys.executable, str(Path(__file__).with_name(scenario))], env=env, check=True)
