#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Assert UAT6 Dev startup signs in without a command-line login helper.

Launch an isolated MIXAR_QA=1 profile with native credential storage redirected
in memory, the bundle startup module installed, and only qa_server.py passed
via --python. Run with QA_HARNESS and MIXAR_QA_PORT set.
"""
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario


def run(qa):
    qa.step('startup_account_signed_in', qa.wait,
            'bpy.context.window_manager.mixie_chat_is_logged_in and '
            'not bpy.context.window_manager.mixie_chat_is_guest', timeout=90)
    state = qa.eval("import os\nfrom mixar.config.config import get_dev_bypass_credentials,get_server_url\nassert os.environ.get('MIXAR_QA')=='1'\nassert get_server_url().rstrip('/')=='https://uat6.mixar.app'\nusername,password=get_dev_bypass_credentials()\nassert username and password\nwm=bpy.context.window_manager\nfrom mixar.modules.auth.core.auth import get_access_token,user_id_from_token\nassert user_id_from_token(get_access_token())=='6e65d4a3-1948-4c15-b884-511c06b3c919'\nresult={'signed_in':wm.mixie_chat_is_logged_in,'guest':wm.mixie_chat_is_guest,'expected_uat6_account_matches':True}")
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/private/tmp/uat6-auto-login-evidence'))
    out.mkdir(parents=True, exist_ok=True)
    qa.snap(str(out / 'signed-in-startup.png'))
    return {'state': state, 'snaps': [str(out / 'signed-in-startup.png')]}


if __name__ == '__main__':
    run_scenario('uat6_auto_dev_login_e2e', run)
