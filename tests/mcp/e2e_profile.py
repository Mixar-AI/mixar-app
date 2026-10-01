# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Verify MCP setup in Profile, absent from Help, in an isolated Dev QA app.

Use the loopback fixture and launcher documented in
docs/development/mixar-mcp-validation.md. No model or paid tool calls.
"""

import argparse
import json
from pathlib import Path
import time

from e2e_scene import enable_in_ui, load_qa


CONNECT = {"op": "MIXAR_OT_connect_ai", "popup": True}
PROFILE = {"but_type": "Popover", "area_type": "TOPBAR"}


def snap(qa, path, target):
    # Flush the popup's host window before reading its framebuffer.
    qa.eval(f"w=drv.find_one(**{target!r})['_win']\n"
            "with bpy.context.temp_override(window=w, area=next(iter(w.screen.areas))):\n"
            " bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)\nresult=True")
    qa.cmd("snap", path=str(path), target=target, margin=1500)


def close_popups(qa):
    for _ in range(3):
        widgets = qa.find(popup=True)["widgets"]
        if not widgets:
            return
        for window in {w["window"] for w in widgets}:
            qa.press("ESC", window=window)
    assert not qa.find(popup=True)["total"]


def profile_layout(qa, output):
    saved = qa.eval("result=bpy.context.preferences.view.ui_scale")
    layouts = {}
    try:
        for factor in (1.0, 1.5):
            qa.eval(f"bpy.context.preferences.view.ui_scale={saved * factor}\nresult=True")
            qa.click(**PROFILE)
            names = ("Dashboard", "Refer a Friend", "AI Provider Settings", "Connect MCP", "Docs")
            rows = {name: qa.find(text=name, popup=True)["widgets"][0]["rect"] for name in names}
            top, right, settings, connect, bottom = (rows[name] for name in names)
            # The same painter inset surrounds each button; equal layout gaps
            # therefore produce equal visible gaps across rows and columns.
            gaps = [right[0] - top[2], top[1] - settings[3],
                    settings[1] - connect[3], connect[1] - bottom[3]]
            assert min(gaps) >= -1, (factor, gaps)
            assert max(gaps) - min(gaps) <= 1, (factor, gaps)
            assert max(r[0] for r in (top, settings, connect, bottom)) - min(
                r[0] for r in (top, settings, connect, bottom)) <= 1, rows
            assert abs(settings[2] - connect[2]) <= 1, rows
            heights = [r[3] - r[1] for r in rows.values()]
            assert max(heights) - min(heights) <= 1, heights
            snap(qa, output / ("profile.png" if factor == 1 else "profile-150.png"), CONNECT)
            layouts[str(factor)] = {"rects": rows, "gaps": gaps}
            close_popups(qa)
    finally:
        close_popups(qa)
        qa.eval(f"bpy.context.preferences.view.ui_scale={saved}\nresult=True")
    return layouts


def run(qa, output):
    deadline = time.monotonic() + 45
    while True:
        try:
            qa.status()
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.25)
    qa.cmd("wait_login", timeout=45)
    qa.eval("import os\nfrom mixar.config.config import get_server_url\n"
            "assert os.environ.get('MIXAR_QA') == '1' and bpy.app.use_event_simulate\n"
            "assert get_server_url().startswith(('http://127.0.0.1:', 'http://localhost:'))\n"
            "result=True")
    close_popups(qa)
    qa.click(text="Help", but_type="Pulldown")
    assert qa.find(text="Documentation", popup=True)["total"] == 1
    assert qa.find(**CONNECT)["total"] == 0
    snap(qa, output / "help.png", {"text": "Documentation", "popup": True})
    close_popups(qa)

    email = qa.eval("result=drv.main_window().scene.mixie_chat_user_id")
    qa.click(text=email, area_type="TOPBAR")
    entry = qa.find(**CONNECT)["widgets"]
    assert len(entry) == 1 and entry[0]["enabled"], entry
    assert entry[0]["text"] == "Connect MCP", entry
    assert qa.find(op="MIXAR_BYOK_OT_open_dialog", popup=True)["total"] == 1
    close_popups(qa)
    layouts = profile_layout(qa, output)
    enable_in_ui(qa, output)
    qa.click(text=email, area_type="TOPBAR")
    qa.click(**CONNECT)
    assert qa.find(text="MCP enabled", popup=True)["total"] == 1
    assert qa.find(op="MIXAR_OT_copy_mcp_setup", popup=True)["total"] == 3
    qa.click(op="MIXAR_OT_set_mcp_enabled", text="Disable", popup=True)
    qa.wait("not __import__('mixar.modules.mcp_bridge.core.runtime', fromlist=['enabled']).enabled()",
            timeout=10)
    close_popups(qa)

    # Exercise the Python fallback used by builds without the native card.
    qa.eval("p=bpy.types.MIXAR_PT_profile\np._qa_native_draw=p.draw\n"
            "p.draw=lambda self, context: self._draw_fallback_menu(context, self.layout)\nresult=True")
    try:
        qa.click(text=email, area_type="TOPBAR")
        assert qa.find(**CONNECT)["total"] == 1
        snap(qa, output / "profile-fallback.png", CONNECT)
        qa.click(**CONNECT)
        assert qa.find(op="MIXAR_OT_set_mcp_enabled", popup=True)["total"] == 1
    finally:
        close_popups(qa)
        qa.eval("p=bpy.types.MIXAR_PT_profile\np.draw=p._qa_native_draw\n"
                "del p._qa_native_draw\nresult=True")
    return {"help_entry_absent": True, "profile_entry_enabled": True,
            "profile_label": "Connect MCP", "layout_at_ui_scales": layouts,
            "setup_opens": True, "enable_connect_disable": True,
            "client_setup_choices": 3, "fallback_setup_opens": True,
            "credits_spent": 0, "requires_visual_review": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qa-harness", type=Path, required=True)
    parser.add_argument("--qa-port", type=int, default=4797)
    parser.add_argument("--out", type=Path, required=True)
    options = parser.parse_args()
    options.out.mkdir(parents=True, exist_ok=True)
    verdict = run(load_qa(options.qa_harness, options.qa_port), options.out)
    (options.out / "verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
    print(json.dumps(verdict))


if __name__ == "__main__":
    main()
