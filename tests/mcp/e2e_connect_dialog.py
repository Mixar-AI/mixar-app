# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay Help > Connect AI Apps (MCP) the way a user clicks it.

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
    qa.click(text="Help", but_type="Pulldown")
    time.sleep(0.6)
    qa.click(op="MIXAR_OT_connect_ai", popup=True)
    time.sleep(1.0)
    qa.snap(str(out / "dialog-mcp-off.png"))
    checkbox = widgets(op="MIXAR_OT_set_mcp_ui_control")
    check("interface_checkbox_needs_mcp", checkbox and checkbox[0].get("enabled") is False, checkbox)

    qa.click(text="Copy MCP Config", op="MIXAR_OT_copy_mcp_setup", popup=True)
    time.sleep(0.6)
    copied = qa.eval("import json\nfrom mixar.modules.mcp_bridge.core import runtime\n"
                     "m=json.loads(bpy.context.window_manager.clipboard)['mcpServers']['mixar']\n"
                     "result={'mcp':runtime.enabled(),'command':m['command'],'args':m['args']}")
    check("copy_mcp_config_enables_and_copies_standard_json",
          copied["mcp"] and copied["command"].endswith("connector/mixar-mcp") and copied["args"] == [], copied)

    qa.click(op="MIXAR_OT_set_mcp_ui_control", popup=True)
    time.sleep(0.6)
    ui = qa.eval("from mixar.modules.mcp_bridge.core import runtime\nresult=runtime.ui_control_enabled()")
    check("checkbox_turns_interface_control_on", ui is True)
    qa.snap(str(out / "dialog-mcp-on.png"))

    qa.eval(STORE + "s.clear_all()\nresult=True")
    qa.click(op="MIXAR_OT_mcp_add_to_app", popup=True)
    shown = toast("Claude Code")
    entry = subprocess.run(["claude", "mcp", "get", "mixar"], capture_output=True, text=True,
                           env={**__import__("os").environ, "CLAUDE_CONFIG_DIR": facts["claude"]}).stdout
    check("add_to_claude_code", ("success", "Mixar added to Claude Code") in [tuple(t) for t in shown]
          and copied["command"] in entry, {"toast": shown, "entry": entry[:300]})
    qa.snap(str(out / "added-claude-code.png"))

    qa.cmd("choose", widget={"prop": "app", "popup": True}, item="Codex")
    time.sleep(0.6)
    for attempt, expected in ((1, "Mixar added to Codex"), (2, "Codex already has Mixar")):
        qa.eval(STORE + "s.clear_all()\nresult=True")
        qa.click(op="MIXAR_OT_mcp_add_to_app", popup=True)
        shown = toast("Codex")
        check(f"add_to_codex_click_{attempt}", any(title == expected for _, title in shown), shown)
    text = codex_config.read_text()
    check("codex_config_keeps_existing_settings_and_one_mixar_table",
          text.startswith(EXISTING_CODEX.rstrip("\n")) and text.count("[mcp_servers.mixar]") == 1
          and "tool_timeout_sec = 610" in text and codex_config.with_name("config.toml.mixar-backup").exists(), text)

    qa.cmd("choose", widget={"prop": "app", "popup": True}, item="Cursor")
    time.sleep(0.6)
    qa.click(text="Copy", op="MIXAR_OT_copy_mcp_setup", popup=True)
    time.sleep(0.6)
    cursor = qa.eval("import json\nresult=json.loads(bpy.context.window_manager.clipboard)['mcpServers']['mixar']")
    check("cursor_copy_is_stdio_json", cursor.get("type") == "stdio" and cursor["command"] == copied["command"])
    check("cursor_offers_open_config_file", bool(widgets(op="MIXAR_OT_mcp_open_app_config")))
    qa.snap(str(out / "dialog-cursor.png"))
    verdict["ok"] = True
    check("all", True)
    print(json.dumps({"ok": True, "evidence": str(out / "dialog-verdict.json")}))


if __name__ == "__main__":
    main()
