# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Free replay against an isolated QA app. Does not install or quit.

QA_HARNESS points to mixar-qa-harness; MIXAR_QA_PORT selects the app.
QA_LOAD_SOURCE=1 hot-loads the checkout's badge. QA_EVIDENCE sets output.
Seeds READY without a real download and intercepts only apply_and_restart;
real header/toast events and the registered confirmation operator run.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import QA, run_scenario

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(os.environ.get("QA_EVIDENCE", "/tmp/header-restart-update"))


def run(qa: QA):
    def ev(code):
        return qa.eval("if not hasattr(drv, 'qa_update_ns'): drv.qa_update_ns = {'bpy': bpy, 'drv': drv}\n"
                       + f"exec({code!r}, drv.qa_update_ns)\n"
                       + "result = drv.qa_update_ns.get('result')")

    def snap(name, **kwargs):
        # Present Metal frames so pixels include the popup already in the dump.
        ev('with bpy.context.temp_override(window=drv.main_window()):\n'
           '    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)\n'
           'result = True')
        return qa.cmd("snap", path=str(OUT / name), **kwargs)

    OUT.mkdir(parents=True, exist_ok=True)
    qa.cmd("wait_login", timeout=60)
    qa.press("ESC")
    ev('''from mixar.modules.common.updates.core import install_flow, toasts
from mixar.modules.common.updates.core.state import UpdateInfo, get_update_state
from mixar.modules.common.updates.ui import topbar_badge
from mixar.modules.common.notifications.store import get_notification_store
from mixar.modules.common.updates.constants import UPDATE_NOTIFICATION_ID
qa_old_apply = install_flow.apply_and_restart
qa_old_badge = topbar_badge.draw_update_badge.__code__
qa_update_calls = []
def qa_apply():
    qa_update_calls.append("apply_and_restart")
    return True, ""
install_flow.apply_and_restart = qa_apply
state = get_update_state()
state.set_available(UpdateInfo(latest_version="99.0.0", current_version="4.1.4",
    download_url="https://example.invalid/qa.dmg", download_sha256="b" * 64,
    download_size=1, installer_type="dmg"))
state.set_ready("/tmp/qa-not-an-installer.dmg", True)
get_notification_store().dismiss(UPDATE_NOTIFICATION_ID)
topbar_badge.tag_topbar_redraw()
result = True
''')
    try:
        snap("before.png", area="TOPBAR")
        if os.environ.get("QA_LOAD_SOURCE") == "1":
            # Preserve function identity: topbar consumers may import it directly.
            path = ROOT / "src/scripts/mixar/modules/common/updates/ui/topbar_badge.py"
            ev(f'''qa_badge_ns = dict(topbar_badge.__dict__)
exec(compile(open({str(path)!r}).read(), {str(path)!r}, "exec"), qa_badge_ns)
topbar_badge.draw_update_badge.__code__ = qa_badge_ns["draw_update_badge"].__code__
topbar_badge.tag_topbar_redraw()
result = True
''')
        qa.wait('bool(drv.find(op="MIXAR_OT_restart_to_update", area_type="TOPBAR"))')
        snap("header-ready.png", area="TOPBAR")

        def dialog(source):
            if source == "header":
                qa.click(op="MIXAR_OT_restart_to_update", area_type="TOPBAR")
            else:
                ev('toasts.push_update_available_toast(state.update_info); result = True')
                qa.wait('bool(drv.find(surface="toast_action", text="Restart & Update"))')
                qa.click(surface="toast_action", text="Restart & Update")
            qa.wait('bool(drv.find(popup=True, text="Restart & Update"))')
            assert ev('result = not qa_update_calls'), "Restart ran before confirmation"
            snap(source + "-confirmation.png")
            return ev('result = [w.get("text") for w in drv.find(popup=True)]')

        header = qa.step("header_confirmation", dialog, "header")
        qa.press("ESC")
        assert ev('result = not qa_update_calls and state.install_state.value == "ready"')
        toast = qa.step("notification_confirmation", dialog, "toast")
        assert header == toast, "Header and notification dialogs differ"
        qa.press("ESC")
        qa.step("header_confirm_again", dialog, "header")
        qa.click(popup=True, text="OK")
        qa.wait('drv.qa_update_ns["qa_update_calls"] == ["apply_and_restart"]')
        qa.cmd("snap", path=str(OUT / "confirmed.png"))
        verdict = {"ok": True, "same_confirmation": True,
                   "cancel_keeps_ready": True, "installer_handoff": True,
                   "screenshots": str(OUT), "steps": qa.log}
        (OUT / "verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
        return {key: value for key, value in verdict.items() if key != "ok"}
    finally:
        qa.press("ESC")
        ev('''install_flow.apply_and_restart = qa_old_apply
topbar_badge.draw_update_badge.__code__ = qa_old_badge
get_notification_store().dismiss(UPDATE_NOTIFICATION_ID)
state.set_idle()
topbar_badge.tag_topbar_redraw()
result = True
''')


if __name__ == "__main__":
    run_scenario("header_restart_update", run)
