# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay the Connect MCP sheet the way a user clicks it: Other app's
JSON, the interface switch, Add to Claude Code / Codex landing on the sheet's
recap (no toast while it is open), a toast once it is closed, Cursor's Copy
setup and Open mcp.json.

Event-simulate QA app (e2e_launch.py without --normal-input), launched with
CLAUDE_CONFIG_DIR and CODEX_HOME pointing INSIDE the fixture: Add to Claude
Code / Codex really run, so the scenario refuses to start otherwise and never
touches a real user's configuration. Requires the `claude` CLI. Spends no
credits. Read the emitted PNGs before claiming visual acceptance.
"""

import argparse
import json
from pathlib import Path
import subprocess
import time

from e2e_scene import load_qa

STORE = "s=__import__('mixar.modules.common.notifications.store',fromlist=['x']).get_notification_store()\n"
EXISTING_CODEX = '# existing user settings\nmodel = "gpt-6"\n\n[mcp_servers.other]\ncommand = "other-server"\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--harness", type=Path, required=True)
    parser.add_argument("--port", type=int, default=4797)
    options = parser.parse_args()
    fixture = options.fixture.resolve()
    out = fixture / "connect-dialog"
    out.mkdir(exist_ok=True)
    qa = load_qa(options.harness, options.port)
    verdict = {"checks": {}}

    def check(name, ok, detail=None):
        verdict["checks"][name] = {"ok": bool(ok), "detail": detail}
        (out / "dialog-verdict.json").write_text(json.dumps(verdict, indent=2, default=str))
        print(("[scenario] OK   " if ok else "[scenario] FAIL ") + name, flush=True)
        if not ok:
            raise AssertionError(f"{name}: {detail}")

    def widgets(**query):
        found = qa.find(popup=True, limit=80, **query)
        return found.get("widgets", found) if isinstance(found, dict) else found

    def toast(app):
        qa.wait(f"any({app!r} in (n.title or '') for n in __import__('mixar.modules.common.notifications.store',"
                "fromlist=['x']).get_notification_store().get_visible())", timeout=60)
        return qa.eval(STORE + "result=[(n.type.value,n.title) for n in s.get_visible()]")

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
                    "'backend':get_server_url(),'claude':os.environ.get('CLAUDE_CONFIG_DIR',''),"
                    "'codex':os.environ.get('CODEX_HOME','')}")
    inside = all(facts[key].startswith(str(fixture)) for key in ("claude", "codex"))
    if not (facts["qa"] and facts["sim"] and facts["backend"].startswith("http://127.0.0.1:") and inside):
        raise RuntimeError("Run only in an isolated event-simulate QA app whose CLAUDE_CONFIG_DIR and "
                           "CODEX_HOME are inside the fixture")
    codex_config = Path(facts["codex"]) / "config.toml"
    codex_config.parent.mkdir(parents=True, exist_ok=True)
    codex_config.write_text(EXISTING_CODEX)

    qa.dismiss_splash()
    state = "result=bpy.context.window_manager.mixar_mcp_dialog_state"

    def open_sheet():
        qa.eval("result = list(bpy.ops.mixar.connect_ai('INVOKE_DEFAULT'))")
        time.sleep(1.0)
        check(f"sheet_opens_idle_{len(verdict['checks'])}", qa.eval(state) == "IDLE")

    def pick(name):
        qa.click(text=name, op="MIXAR_OT_mcp_pick_app", popup=True)
        time.sleep(0.6)

    def add_and_wait(name, expected):
        """Add from the open sheet: the sheet flips to its recap by itself
        (redraw pump) and no toast is pushed while it is open."""
        qa.eval(STORE + "s.clear_all()\nresult=True")
        qa.click(text=f"Add to {name}", op="MIXAR_OT_mcp_add_to_app", popup=True)
        qa.wait("bpy.context.window_manager.mixar_mcp_dialog_state in {'ADDED', 'ERROR'}", timeout=60)
        time.sleep(0.6)
        recap = widgets(text=expected)
        toasts = qa.eval(STORE + "result=[n.title for n in s.get_visible()]")
        check(f"add_to_{name.lower().replace(' ', '_')}_recap_{expected!r}",
              qa.eval(state) == "ADDED" and bool(recap) and not toasts,
              {"state": qa.eval(state), "recap": recap, "toasts": toasts})

    # The profile-menu entry itself is covered by e2e_profile.py (native card and
    # Python fallback); this replay is about the sheet.
    open_sheet()
    qa.snap(str(out / "dialog-mcp-off.png"))
    switch = widgets(op="MIXAR_OT_set_mcp_ui_control")
    check("interface_switch_needs_mcp", switch and switch[0].get("enabled") is False, switch)
    check("mcp_off_offers_turn_on", bool(widgets(text="Turn on", op="MIXAR_OT_set_mcp_enabled")))

    pick("Other app")
    qa.click(text="Copy setup", op="MIXAR_OT_copy_mcp_setup", popup=True)
    time.sleep(0.6)
    copied = qa.eval("import json\nfrom mixar.modules.mcp_bridge.core import runtime\n"
                     "m=json.loads(bpy.context.window_manager.clipboard)['mcpServers']['mixar']\n"
                     "result={'mcp':runtime.enabled(),'command':m['command'],'args':m['args']}")
    check("other_app_copy_enables_and_copies_standard_json",
          copied["mcp"] and copied["command"].endswith("connector/mixar-mcp") and copied["args"] == [], copied)
    qa.snap(str(out / "dialog-other-app.png"))

    qa.click(op="MIXAR_OT_set_mcp_ui_control", popup=True)
    time.sleep(0.6)
    ui = qa.eval("from mixar.modules.mcp_bridge.core import runtime\nresult=runtime.ui_control_enabled()")
    check("switch_turns_interface_control_on", ui is True)
    check("mcp_on_offers_turn_off", bool(widgets(text="Turn off", op="MIXAR_OT_set_mcp_enabled")))

    pick("Claude Code")
    check("claude_code_docks_copy_in_its_snippet",
          len(widgets(op="MIXAR_OT_copy_mcp_setup")) == 1 and bool(widgets(text="Copy")))
    qa.snap(str(out / "dialog-mcp-on.png"))
    add_and_wait("Claude Code", "Mixar added to Claude Code")
    entry = subprocess.run(["claude", "mcp", "get", "mixar"], capture_output=True, text=True,
                           env={**__import__("os").environ, "CLAUDE_CONFIG_DIR": facts["claude"]}).stdout
    check("add_to_claude_code", copied["command"] in entry, {"entry": entry[:300]})
    qa.snap(str(out / "added-claude-code.png"))
    qa.click(text="Done", popup=True)
    time.sleep(0.6)
    check("done_closes_the_sheet", not widgets(op="MIXAR_OT_mcp_pick_app"))

    for attempt, expected in ((1, "Mixar added to Codex"), (2, "Codex already has Mixar")):
        open_sheet()
        pick("Codex")
        add_and_wait("Codex", expected)
        qa.snap(str(out / f"added-codex-{attempt}.png"))
        qa.click(text="Done", popup=True)
        time.sleep(0.6)
    text = codex_config.read_text()
    check("codex_config_keeps_existing_settings_and_one_mixar_table",
          text.startswith(EXISTING_CODEX.rstrip("\n")) and text.count("[mcp_servers.mixar]") == 1
          and "tool_timeout_sec = 610" in text and codex_config.with_name("config.toml.mixar-backup").exists(), text)

    # With the sheet closed the outcome still reaches the user, as a toast.
    qa.eval(STORE + "s.clear_all()\nresult=True")
    qa.eval("result = list(bpy.ops.mixar.mcp_add_to_app(app='CODEX'))")
    shown = toast("Codex")
    check("a_closed_sheet_gets_a_toast", ("info", "Codex already has Mixar") in [tuple(t) for t in shown], shown)

    open_sheet()
    pick("Cursor")
    qa.click(text="Copy setup", op="MIXAR_OT_copy_mcp_setup", popup=True)
    time.sleep(0.6)
    cursor = qa.eval("import json\nresult=json.loads(bpy.context.window_manager.clipboard)['mcpServers']['mixar']")
    check("cursor_copy_is_stdio_json", cursor.get("type") == "stdio" and cursor["command"] == copied["command"])
    check("cursor_offers_open_config_file", bool(widgets(text="Open mcp.json", op="MIXAR_OT_mcp_open_app_config")))
    qa.snap(str(out / "dialog-cursor.png"))
    verdict["ok"] = True
    check("all", True)
    print(json.dumps({"ok": True, "evidence": str(out / "dialog-verdict.json")}))


if __name__ == "__main__":
    main()
