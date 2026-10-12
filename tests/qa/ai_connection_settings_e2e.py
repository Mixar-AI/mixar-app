#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay AI setup guidance without real credentials or external app writes.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4793 \
 QA_SCENARIO_OUT=/tmp/ai-settings python3 tests/qa/ai_connection_settings_e2e.py

Use QA_CAPTURE_BEFORE=1 against the preceding installed build for baseline PNGs.
Requires an isolated event-simulate QA app. HTTP/catalog boundaries are fixtures;
forms, clipboard paste, popup events and screenshots run in the real app.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from profile_provider_settings_e2e import SETUP, CLEANUP, close_popup, snap as provider_snap

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/ai-settings'))
OUT.mkdir(parents=True, exist_ok=True)
BEFORE = os.environ.get('QA_CAPTURE_BEFORE') == '1'
SAVE = {'op': 'MIXAR_BYOK_OT_save', 'popup': True}


def snap(qa, name, target):
    # Native popups can have geometry before their first presented frame.
    # Move over a semantic target to run the normal popup redraw path.
    qa.eval(f"w=drv.find_one(**{target!r})\n"
            "drv.move_to(w['_win'], *w['center'])\nresult=True")
    time.sleep(.3)
    return provider_snap(qa, name, target)


def run(qa):
    qa.eval("import os\nassert os.environ.get('MIXAR_QA') == '1'\n"
            "assert bpy.app.use_event_simulate\n"
            "assert '/tmp/' in os.environ.get('MIXAR_USER_RESOURCES', '')\nresult=True")
    qa.press("ESC")
    qa.eval(SETUP)
    expired = qa.eval("result=bpy.context.window_manager.mixie_chat_session_expired")
    qa.eval("bpy.context.window_manager.mixie_chat_session_expired=False\nresult=True")
    paths = []
    try:
        qa.eval("result=str(bpy.ops.mixar_byok.open_dialog('INVOKE_DEFAULT'))")
        qa.wait("bool(drv.find(op='MIXAR_BYOK_OT_save', popup=True))", timeout=10)
        paths.append(snap(qa, 'api_key_setup', SAVE))
        qa.cmd('choose', widget={'prop': 'byok_form_provider', 'popup': True},
               item='Codex (ChatGPT sub)' if BEFORE else 'Codex (ChatGPT sign-in)')
        qa.wait("bool(drv.find(op='MIXAR_BYOK_OT_codex_paste', popup=True))", timeout=5)
        paths.append(snap(qa, 'codex_empty', SAVE))
        if not BEFORE:
            assert not qa.find(prop='byok_form_codex_bundle', popup=True)['widgets']
            # No real credential is read. Paste only the synthetic bundle, then
            # Escape proves the dialog still clears transient secret material.
            qa.eval("bpy.context.window_manager.clipboard='qa-synthetic-sign-in'\nresult=True")
            qa.click(op='MIXAR_BYOK_OT_codex_paste', popup=True)
            qa.wait("bpy.context.window_manager.byok_form_codex_bundle == 'qa-synthetic-sign-in'", timeout=5)
            paths.append(snap(qa, 'codex_loaded', SAVE))
        close_popup(qa)
        qa.eval("assert not bpy.context.window_manager.byok_form_codex_bundle\n"
                "result=str(bpy.ops.mixar.connect_ai('INVOKE_DEFAULT'))")
        qa.wait("bool(drv.find(op='MIXAR_OT_set_mcp_enabled', popup=True))", timeout=5)
        paths.append(snap(qa, 'mcp_simple', {'op': 'MIXAR_OT_set_mcp_enabled', 'popup': True}))
        if not BEFORE:
            assert not qa.find(text='Copy MCP Config', popup=True)['widgets']
            qa.click(prop='show_manual', popup=True)
            qa.wait("bool(drv.find(text='Copy MCP Config', popup=True))", timeout=5)
            paths.append(snap(qa, 'mcp_manual', {'prop': 'show_manual', 'popup': True}))
            # Other apps retain a direct copy action without the advanced panel.
            qa.click(prop='show_manual', popup=True)
            qa.cmd('choose', widget={'prop': 'app', 'popup': True}, item='Cursor')
            qa.wait("bool(drv.find(text='Copy Setup for This App', popup=True))", timeout=5)
            paths.append(snap(qa, 'mcp_cursor', {'op': 'MIXAR_OT_copy_mcp_setup', 'popup': True}))
        close_popup(qa)
        # Signed-out guidance must remain actionable even without setup access.
        qa.eval("bpy.context.window_manager.mixie_chat_is_logged_in=False\n"
                "result=str(bpy.ops.mixar.connect_ai('INVOKE_DEFAULT'))")
        qa.wait("bool(drv.find(op='MIXIE_CHAT_OT_login', popup=True))", timeout=5)
        paths.append(snap(qa, 'mcp_signed_out', {'op': 'MIXIE_CHAT_OT_login', 'popup': True}))
        return {'screenshots': paths, 'baseline': BEFORE,
                'billing': 'no credits spent; no real credentials or app config writes'}
    finally:
        close_popup(qa)
        qa.eval(CLEANUP)
        qa.eval(f"bpy.context.window_manager.mixie_chat_session_expired={expired!r}\nresult=True")
        qa.eval("bpy.context.window_manager.clipboard=''\nresult=True")


if __name__ == '__main__':
    run_scenario('ai_connection_settings_e2e', run)
