# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay the Connect MCP dialog's status line: signed in and
connected, then signed out with MCP still on.

The dialog once said "MCP is on: AI apps can connect to this Mixar." under its
own "Sign in to Mixar" notice, because the line only checked that the local
relay existed. The sheet's status line ("MCP is on · ...") keeps that rule. Event-simulate QA app from e2e_launch.py on a fixture backend
with guest accounts off (the default), so signing out stays signed out.
Spends no credits. Read the emitted PNGs before claiming visual acceptance.
"""

import argparse
import json
from pathlib import Path
import time

from e2e_scene import load_qa

READY = "MCP is on · AI apps can connect to this Mixar"
NOT_READY = "MCP is on · AI apps can use Mixar once it's signed in and connected"
SIGN_IN = "Sign in to connect MCP."
STATE = ("from mixar.modules.mcp_bridge.core import runtime\nwm=bpy.context.window_manager\n"
         "result={'mcp':runtime.enabled(),'running':runtime.is_running(),"
         "'connected':bool(runtime.snapshot().get('connected')),"
         "'signed_in':bool(wm.mixie_chat_is_logged_in) and not wm.mixie_chat_session_expired}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--harness", type=Path, required=True)
    parser.add_argument("--port", type=int, default=4797)
    parser.add_argument("--out", type=Path, help="Evidence folder (default: <fixture>/connect-dialog-status)")
    options = parser.parse_args()
    fixture = options.fixture.resolve()
    out = (options.out or fixture / "connect-dialog-status").resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa = load_qa(options.harness, options.port)
    verdict = {"checks": {}}

    def check(name, ok, detail=None):
        verdict["checks"][name] = {"ok": bool(ok), "detail": detail}
        (out / "status-verdict.json").write_text(json.dumps(verdict, indent=2, default=str))
        # Keep going after a failure so the replay still captures every state.
        print(("[scenario] OK   " if ok else "[scenario] FAIL ") + name, flush=True)

    def dialog_texts():
        found = qa.find(popup=True, limit=200)
        found = found.get("widgets", found) if isinstance(found, dict) else found
        return [widget.get("text", "") for widget in found]

    def open_dialog(shot):
        qa.eval("result = list(bpy.ops.mixar.connect_ai('INVOKE_DEFAULT'))")
        time.sleep(1.0)
        texts = dialog_texts()
        qa.snap(str(out / shot))
        qa.press("ESC")
        time.sleep(0.5)
        return texts

    deadline = time.monotonic() + 120
    while True:
        try:
            qa.cmd("ping")
            break
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)
    qa.cmd("wait_login", timeout=120)
    facts = qa.eval("import os\nfrom mixar.config.config import get_server_url\n"
                    "result={'sim':bpy.app.use_event_simulate,'qa':os.environ.get('MIXAR_QA')=='1',"
                    "'backend':get_server_url()}")
    if not (facts["qa"] and facts["sim"] and facts["backend"].startswith("http://127.0.0.1:")):
        raise RuntimeError("Run only in an isolated event-simulate QA app on a loopback fixture backend")
    qa.dismiss_splash()

    qa.eval("result = list(bpy.ops.mixar.set_mcp_enabled(enabled=True))")
    qa.wait("(lambda r: r.is_running() and bool(r.snapshot().get('connected')))("
            "__import__('mixar.modules.mcp_bridge.core.runtime', fromlist=['x']))", timeout=60)
    state = qa.eval(STATE)
    texts = open_dialog("signed-in-connected.png")
    check("signed_in_connected_says_ai_apps_can_connect",
          state == {"mcp": True, "running": True, "connected": True, "signed_in": True}
          and READY in texts and NOT_READY not in texts and SIGN_IN not in texts,
          {"state": state, "texts": texts})

    qa.eval("result = list(bpy.ops.mixie_chat.logout())")
    qa.wait("not bpy.context.window_manager.mixie_chat_is_logged_in", timeout=30)
    time.sleep(3.0)  # The relay keeps running; let a connector tick refresh its snapshot.
    state = qa.eval(STATE)
    texts = open_dialog("signed-out-mcp-on.png")
    check("signed_out_with_mcp_on_never_says_ai_apps_can_connect",
          state["mcp"] and state["running"] and not state["signed_in"]
          and SIGN_IN in texts and NOT_READY in texts and READY not in texts,
          {"state": state, "texts": texts})
    check("signed_out_can_still_turn_mcp_off", "Turn off" in texts, texts)
    failed = [name for name, entry in verdict["checks"].items() if not entry["ok"]]
    verdict["ok"] = not failed
    (out / "status-verdict.json").write_text(json.dumps(verdict, indent=2, default=str))
    print(json.dumps({"ok": not failed, "failed": failed, "evidence": str(out / "status-verdict.json")}))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
