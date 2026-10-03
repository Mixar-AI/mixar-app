# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Verify MCP setup lives in the profile menu (not Help) and needs a sign-in.

Event-simulate QA app on the loopback fixture (e2e_launch.py without
--normal-input). No model or paid tool calls. Checks: Help has no MCP entry; the
profile card (native, and its Python fallback) offers Connect AI Apps (MCP),
aligned with the other actions at 100% and 150% UI scale, and it opens the
setup dialog; signed out, the dialog offers only Sign In and enabling, Add to
and Copy refuse; signed in, Copy saves the tool list at once. ``--fallback-only``
skips the native card checks (a build made before the native entry existed).
Screenshots go to --out, never into the repository.
"""

import argparse
import json
from pathlib import Path
import time

from e2e_scene import load_qa

LABEL = "Connect AI Apps (MCP)"
CONNECT = {"op": "MIXAR_OT_connect_ai", "popup": True}
PROFILE = {"but_type": "Popover", "area_type": "TOPBAR"}
WM = "bpy.context.window_manager"


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
            names = ("Dashboard", "Refer a Friend", "AI Provider Settings", LABEL, "Docs")
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


def signed_out_setup(qa, output, fixture):
    """Signed out: the dialog offers Sign In, plus Disable while MCP is still on
    (the session expired); enabling paths refuse."""
    saved = fixture / "connector" / "tools.json"
    mcp_on = "__import__('mixar.modules.mcp_bridge.core.runtime',fromlist=['x']).enabled()"
    assert qa.eval("result = list(bpy.ops.mixar.set_mcp_enabled(enabled=True))") == ["FINISHED"]
    qa.eval("result = list(bpy.ops.mixie_chat.logout())")
    qa.wait(f"not {WM}.mixie_chat_is_logged_in", timeout=30)
    saved.unlink(missing_ok=True)
    qa.eval("result = list(bpy.ops.mixar.connect_ai('INVOKE_DEFAULT'))")
    time.sleep(0.8)
    assert qa.find(text="Sign in to Mixar to connect AI apps.", popup=True)["total"] == 1
    assert qa.find(op="MIXIE_CHAT_OT_login", popup=True)["total"] == 1
    toggles = qa.find(op="MIXAR_OT_set_mcp_enabled", popup=True)["widgets"]
    assert [w["text"] for w in toggles] == ["Disable"], toggles  # Turning off needs no account.
    assert qa.find(op="MIXAR_OT_copy_mcp_setup", popup=True)["total"] == 0
    snap(qa, output / "setup-signed-out.png", {"text": "Sign in to Mixar to connect AI apps.", "popup": True})
    qa.click(op="MIXAR_OT_set_mcp_enabled", popup=True)
    qa.wait(f"not {mcp_on}", timeout=10)
    signed_out_disable = True
    close_popups(qa)
    # An operator's ERROR report reaches a script as RuntimeError.
    refused = {name: qa.eval(f"try:\n result = list(bpy.ops.mixar.{name}())\n"
                             "except RuntimeError as exc:\n result = str(exc)")
               for name in ("set_mcp_enabled", "copy_mcp_setup")}
    assert all("Sign in to Mixar before connecting AI apps" in str(r) for r in refused.values()), refused
    qa.eval("result = list(bpy.ops.mixie_chat.login())")
    qa.wait(f"{WM}.mixie_chat_is_logged_in", timeout=90)
    assert qa.eval("result = list(bpy.ops.mixar.copy_mcp_setup(client='JSON'))") == ["FINISHED"]
    deadline = time.monotonic() + 30
    while not saved.exists() and time.monotonic() < deadline:
        time.sleep(0.5)
    assert saved.exists(), "Copy did not save the tool list"
    return {"refused_signed_out": refused, "saved_on_copy": True, "signed_out_can_disable": signed_out_disable}


def run(qa, output, fixture, fallback_only):
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
    qa.dismiss_splash()
    close_popups(qa)
    qa.click(text="Help", but_type="Pulldown")
    assert qa.find(text="Documentation", popup=True)["total"] == 1
    assert qa.find(**CONNECT)["total"] == 0
    snap(qa, output / "help.png", {"text": "Documentation", "popup": True})
    close_popups(qa)
    verdict = {"help_entry_absent": True, "label": LABEL}
    verdict["sign_in"] = signed_out_setup(qa, output, fixture)

    email = qa.eval("result=drv.main_window().scene.mixie_chat_user_id")
    # The top bar swaps "Login" for the account on its next redraw after sign-in.
    qa.wait("bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1) and "
            f"any(w.get('text') == {email!r} for w in drv.find(area_type='TOPBAR'))", timeout=30)
    if not fallback_only:
        qa.click(text=email, area_type="TOPBAR")
        entry = qa.find(**CONNECT)["widgets"]
        assert len(entry) == 1 and entry[0]["enabled"], entry
        assert entry[0]["text"] == LABEL, entry
        assert qa.find(op="MIXAR_BYOK_OT_open_dialog", popup=True)["total"] == 1
        close_popups(qa)
        verdict["layout_at_ui_scales"] = profile_layout(qa, output)
        qa.click(text=email, area_type="TOPBAR")
        qa.click(**CONNECT)
        assert qa.find(text="MCP enabled", popup=True)["total"] == 1
        assert qa.find(op="MIXAR_OT_copy_mcp_setup", popup=True)["total"] >= 2
        snap(qa, output / "setup-from-profile.png", {"text": "MCP enabled", "popup": True})
        close_popups(qa)
        verdict["native_profile_entry_opens_setup"] = True

    # The Python fallback used by builds without the native card.
    qa.eval("p=bpy.types.MIXAR_PT_profile\np._qa_native_draw=p.draw\n"
            "p.draw=lambda self, context: self._draw_fallback_menu(context, self.layout)\nresult=True")
    try:
        qa.click(text=email, area_type="TOPBAR")
        assert qa.find(**CONNECT)["total"] == 1
        snap(qa, output / "profile-fallback.png", CONNECT)
        qa.click(**CONNECT)
        assert qa.find(text="MCP enabled", popup=True)["total"] == 1
    finally:
        close_popups(qa)
        qa.eval("p=bpy.types.MIXAR_PT_profile\np.draw=p._qa_native_draw\n"
                "del p._qa_native_draw\nresult=True")
    verdict.update(fallback_entry_opens_setup=True, credits_spent=0, requires_visual_review=True)
    return verdict


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qa-harness", type=Path, required=True)
    parser.add_argument("--qa-port", type=int, default=4797)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fallback-only", action="store_true",
                        help="Skip the native profile card (a build without its Connect entry)")
    options = parser.parse_args()
    options.out.mkdir(parents=True, exist_ok=True)
    verdict = run(load_qa(options.qa_harness, options.qa_port), options.out, options.fixture.resolve(),
                  options.fallback_only)
    (options.out / "verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
    print(json.dumps(verdict))


if __name__ == "__main__":
    main()
