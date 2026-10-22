#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Codex in AI Provider Settings: a found sign-in is prefilled, Save just works.

Run against an isolated offline QA instance. `CODEX_HOME` points at a temp
folder holding a synthetic auth.json (fake tokens, never a real sign-in) and
the save stops at `byok_client.save_credentials`, so nothing is sent. The
dialog, its prefill, the click on Save & Activate and the sheet's drawing are
real. All replaced state is restored.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4791 \
    QA_SCENARIO_OUT=/tmp/codex-prefill-qa python3 tests/qa/byok_codex_prefill_e2e.py
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/codex-prefill-qa'))
OUT.mkdir(parents=True, exist_ok=True)
SAVE = {'op': 'MIXAR_BYOK_OT_save', 'popup': True}
WM = 'bpy.context.window_manager'

SETUP = """
import bpy, copy, os, tempfile
from types import SimpleNamespace
from mixar.modules.byok.core import model_suggestions as M
from mixar.modules.byok.ui.operators import byok_codex_ops as X
assert os.environ.get('MIXAR_QA') == '1'
wm = bpy.context.window_manager
home = tempfile.mkdtemp(prefix='qa-codex-home-')
saved = (os.environ.get('CODEX_HOME'), X.byok_client.save_credentials,
         list(M._provider_cache), copy.deepcopy(M._model_cache),
         copy.deepcopy(M._platform_records), M.is_loaded(),
         wm.byok_form_codex_path, bpy.context.preferences.view.show_tooltips)
os.environ['CODEX_HOME'] = home
fixture = SimpleNamespace(home=home, saves=[])
X.byok_client.save_credentials = lambda **kw: fixture.saves.append(
    {k: v for k, v in kw.items() if k not in ('api_key', 'on_done')})
M.populate_from_payload({'providers': [{'id': 'openai', 'label': 'QA Provider', 'short_label': 'OpenAI API',
    'models': [{'id': 'qa-one', 'label': 'QA Model One', 'short_label': 'QA Model One', 'platform_available': True}]}],
    'provider_order': ['openai', 'codex', 'anthropic', 'gemini', 'openrouter', 'local']})
wm.byok_form_codex_path = ''
wm.byok_form_provider = 'codex'
bpy.context.preferences.view.show_tooltips = False
X._qa_codex_fixture = (saved, fixture)
result = True
"""

# A synthetic bundle: the access token is an unsigned JWT carrying only the
# ChatGPT account-id claim, the refresh token a placeholder.
SIGN_IN = """
import base64, json, os
from mixar.modules.byok.ui.operators import byok_codex_ops as X
def seg(o):
    return base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip('=')
claims = {'https://api.openai.com/auth': {'chatgpt_account_id': 'qa-account'}}
home = X._qa_codex_fixture[1].home
with open(os.path.join(home, 'auth.json'), 'w') as f:
    json.dump({'tokens': {'access_token': seg({'alg': 'none'}) + '.' + seg(claims) + '.sig',
                          'refresh_token': 'qa-refresh-placeholder'}}, f)
result = os.path.join(home, 'auth.json')
"""

CLEANUP = """
import os, shutil
from mixar.modules.byok.core import model_suggestions as M
from mixar.modules.byok.ui.operators import byok_codex_ops as X
saved, fixture = X._qa_codex_fixture
if saved[0] is None:
    os.environ.pop('CODEX_HOME', None)
else:
    os.environ['CODEX_HOME'] = saved[0]
X.byok_client.save_credentials = saved[1]
M.populate(saved[2], saved[3], saved[4])
M._populated_once = saved[5]
wm = bpy.context.window_manager
wm.byok_form_codex_path = saved[6]
wm.byok_dialog_state = 'IDLE'
wm.byok_last_error = ''
bpy.context.preferences.view.show_tooltips = saved[7]
shutil.rmtree(fixture.home, ignore_errors=True)
del X._qa_codex_fixture
result = True
"""


def open_dialog(qa):
    qa.eval("win = drv.main_window()\n"
            "area = max(win.screen.areas, key=lambda a: a.width * a.height)\n"
            "with bpy.context.temp_override(window=win, area=area):\n"
            "    bpy.ops.mixar_byok.open_dialog('INVOKE_DEFAULT')\n"
            "result = True")
    qa.wait("any(w.get('popup') and w.get('op') == 'MIXAR_BYOK_OT_save' "
            "for w in __import__('json').loads(bpy.data.window_managers[0].mixar_qa_ui_dump)['widgets'])",
            timeout=10)


def close_dialog(qa):
    for _ in range(3):
        widgets = qa.find(popup=True)['widgets']
        if not widgets:
            return
        for window in {w['window'] for w in widgets}:
            qa.press('ESC', window=window)
        time.sleep(.2)
    qa.wait('not bool(drv.find(popup=True))', timeout=5)


def snap(qa, name):
    qa.eval(f"widget=drv.find_one(**{SAVE!r})\n"
            "win=widget['_win']\n"
            "area=next(iter(win.screen.areas))\n"
            "with bpy.context.temp_override(window=win, area=area):\n"
            "    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)\n"
            "result=True")
    time.sleep(1)
    path = str(OUT / (name + '.png'))
    qa.step(name + '_snap', qa.cmd, 'snap', path=path, target=SAVE, margin=1500)
    return path


def labels(qa):
    return qa.eval("import json\n"
                   "result = [w.get('text') for w in json.loads("
                   "bpy.data.window_managers[0].mixar_qa_ui_dump)['widgets'] if w.get('popup')]")


FOUND_LINE = 'Codex sign-in found - just click Save & Activate'
MISSING_LINE = 'No Codex sign-in found - run  codex login  in your terminal'


def expect_line(qa, text):
    qa.wait(f"any(w.get('popup') and w.get('text') == {text!r} for w in "
            "__import__('json').loads(bpy.data.window_managers[0].mixar_qa_ui_dump)['widgets'])",
            timeout=5)


def browse_dir(qa, value):
    """Put ``value`` in the path field, press its folder button and return
    the directory the file browser opened on (then cancel it)."""
    qa.eval(f"{WM}.byok_form_codex_path = {value!r}\nresult = True")
    qa.click(op='BUTTONS_OT_file_browse', popup=True)
    qa.wait("any(a.type == 'FILE_BROWSER' for w in bpy.context.window_manager.windows "
            "for a in w.screen.areas)", timeout=10)
    found = qa.eval("result = next(a.spaces.active.params.directory.decode() "
                    "for w in bpy.context.window_manager.windows for a in w.screen.areas "
                    "if a.type == 'FILE_BROWSER')")
    qa.eval("win, area = next((w, a) for w in bpy.context.window_manager.windows "
            "for a in w.screen.areas if a.type == 'FILE_BROWSER')\n"
            "with bpy.context.temp_override(window=win, area=area):\n"
            "    bpy.ops.file.cancel()\n"
            "result = True")
    return found


def run(qa):
    # UI auto-discovery registers the BYOK properties in batches after startup.
    qa.step('byok_registered', qa.wait, f"hasattr({WM}, 'byok_form_codex_path') "
            "and hasattr(bpy.types, 'MIXAR_BYOK_OT_open_dialog')", timeout=60)
    qa.step('install_fixture', qa.eval, SETUP)
    snaps = []
    try:
        # No sign-in yet: the field stays empty and the notes say what to run.
        open_dialog(qa)
        qa.wait(f"{WM}.byok_form_provider == 'codex'", timeout=5)
        if qa.eval(f"result = {WM}.byok_form_codex_path"):
            raise ScenarioFail('Field prefilled without a sign-in file')
        expect_line(qa, MISSING_LINE)
        snaps.append(snap(qa, 'not_signed_in'))
        close_dialog(qa)

        # Signed in: reopening fills the field with the file Save will use.
        auth = qa.step('write_sign_in', qa.eval, SIGN_IN)
        open_dialog(qa)
        qa.wait(f"{WM}.byok_form_codex_path == {auth!r}", timeout=5)
        expect_line(qa, FOUND_LINE)
        snaps.append(snap(qa, 'signed_in_prefilled'))
        texts = labels(qa)

        # One click, no file chosen: the save reads the prefilled default and
        # stores it as empty (the reference keeps following CODEX_HOME).
        # The live catalog may replace the fixture's; any valid lit model will do.
        qa.step('model_selected', qa.wait,
                "__import__('mixar.modules.byok.core.model_suggestions', fromlist=['x'])"
                f".is_valid_model('codex', {WM}.byok_form_model)", timeout=10)
        qa.step('save', qa.click, **SAVE)
        qa.wait("bool(__import__('mixar.modules.byok.ui.operators.byok_codex_ops', "
                "fromlist=['x'])._qa_codex_fixture[1].saves)", timeout=5)
        sent = qa.eval("from mixar.modules.byok.ui.operators import byok_codex_ops as X\n"
                       "result = X._qa_codex_fixture[1].saves")
        if not sent or sent[0].get('codex_auth_path') != '' or sent[0].get('account_id') != 'qa-account':
            raise ScenarioFail(f'Unexpected save: {sent}')
        close_dialog(qa)

        # The prefilled (absolute) path opens the file browser in its folder.
        qa.step('reset_state', qa.eval, f"{WM}.byok_dialog_state = 'IDLE'\nresult = True")
        open_dialog(qa)
        qa.wait(f"{WM}.byok_form_codex_path == {auth!r}", timeout=5)
        browsed = qa.step('browse_prefilled_path', browse_dir, qa, auth)
        want = os.path.dirname(auth)
        if os.path.normpath(browsed) != os.path.normpath(want):
            raise ScenarioFail(f'Browse opened {browsed!r}, expected {want!r}')
        close_dialog(qa)
        return {'snaps': snaps, 'labels': texts, 'saved': sent, 'browsed': browsed}
    finally:
        close_dialog(qa)
        qa.eval(CLEANUP)


if __name__ == '__main__':
    run_scenario('byok_codex_prefill_e2e', run)
