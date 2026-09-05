# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The update toast, rendered from install state, and the operators on it.

The point of the feature is that the toast's primary button is a restart,
not a browser trip — and that it degrades to the browser exactly when the
install cannot update itself.
"""

import ast
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

for _name in ("blf", "gpu", "gpu.state", "gpu.shader", "gpu_extras", "gpu_extras.batch"):
    sys.modules.setdefault(_name, MagicMock(name=_name))

sys.modules.setdefault(
    "mixar.modules.common.utils.mixie_space_utils",
    MagicMock(name="mixie_space_utils"),
)

from mixar.modules.common.notifications.store import get_notification_store
from mixar.modules.common.updates.constants import UPDATE_NOTIFICATION_ID
from mixar.modules.common.updates.core import toasts
from mixar.modules.common.updates.core.state import UpdateInfo, get_update_state

OPERATORS_SRC = (
    SCRIPTS / "mixar" / "modules" / "common" / "updates" / "ui" / "operators.py"
)


def _info(**overrides) -> UpdateInfo:
    defaults = dict(
        latest_version="3.4.0",
        current_version="3.3.6",
        changelog_summary="Faster texture baking.",
        browser_download_url="https://www.mixar.app/downloads",
        download_url="https://cdn.example.com/Mixar-3.4.0-x64.msi",
        download_sha256="b" * 64,
        download_size=400 * 1024 * 1024,
        installer_type="msi",
    )
    defaults.update(overrides)
    return UpdateInfo(**defaults)


def setup_function(_fn):
    get_notification_store().clear_all()
    get_update_state().set_idle()


def _toast():
    for item in get_notification_store().get_visible():
        if item.id == UPDATE_NOTIFICATION_ID:
            return item
    raise AssertionError("update toast not found in store")


def _labels():
    return [action.label for action in _toast().actions]


# ---------------------------------------------------------------------------
# Which button the toast offers
# ---------------------------------------------------------------------------


def test_staged_update_offers_restart_not_a_browser_download():
    state = get_update_state()
    state.set_available(_info())
    state.set_ready("/tmp/Mixar-3.4.0.msi", True)

    toasts.push_update_available_toast(_info())

    assert _labels() == ["Restart & Update"]
    assert _toast().title == "Mixar Update Ready"
    assert "restart" in _toast().body.lower()


def test_restart_is_offered_while_the_installer_is_still_downloading():
    """Clicking early is legitimate — the flow records the intent."""
    state = get_update_state()
    state.set_available(_info())
    state.set_downloading()

    toasts.push_update_available_toast(_info())

    assert _labels() == ["Restart & Update"]


def test_uninstallable_update_falls_back_to_the_downloads_page():
    state = get_update_state()
    state.set_available(_info())
    state.set_install_unsupported("In-app updates aren't supported on this platform")

    toasts.push_update_available_toast(_info())

    assert _labels() == ["Download"]
    download = next(a for a in _toast().actions if a.label == "Download")
    assert download.operator == "mixar.open_downloads_page"


def test_failed_download_falls_back_to_the_downloads_page():
    state = get_update_state()
    state.set_available(_info())
    state.set_install_failed("Download failed")

    toasts.push_update_available_toast(_info())

    assert _labels() == ["Download"]


def test_forced_update_is_not_dismissible():
    state = get_update_state()
    info = _info(force_update=True)
    state.set_available(info)
    state.set_ready("/tmp/Mixar-3.4.0.msi", True)

    toasts.push_update_available_toast(info)

    assert _labels() == ["Restart & Update"]
    assert _toast().dismissible is False


# ---------------------------------------------------------------------------
# Download progress
# ---------------------------------------------------------------------------


def test_progress_toast_replaces_the_buttons_with_cancel():
    state = get_update_state()
    state.set_available(_info())
    state.set_downloading()
    state.set_install_requested(True)
    state.set_download_progress(50 * 1024 * 1024, 400 * 1024 * 1024)

    toasts.push_update_available_toast(_info())

    item = _toast()
    assert item.title == "Downloading Mixar 3.4.0"
    assert "12%" in item.body
    assert "400 MB" in item.body
    assert _labels() == ["Cancel"]


def test_refresh_respects_a_dismissed_toast():
    """Re-rendering on every progress tick must not resurrect the toast."""
    state = get_update_state()
    state.set_available(_info())
    state.set_downloading()
    toasts.push_update_available_toast(_info())
    get_notification_store().dismiss(UPDATE_NOTIFICATION_ID)

    toasts.refresh_update_toast()

    assert get_notification_store().contains(UPDATE_NOTIFICATION_ID) is False


def test_refresh_rerenders_a_visible_toast():
    state = get_update_state()
    state.set_available(_info())
    state.set_downloading()
    toasts.push_update_available_toast(_info())

    state.set_ready("/tmp/Mixar-3.4.0.msi", True)
    toasts.refresh_update_toast()

    assert _toast().title == "Mixar Update Ready"


# ---------------------------------------------------------------------------
# Reporting the previous run's outcome
# ---------------------------------------------------------------------------


def test_failed_install_is_reported_on_the_next_launch(monkeypatch):
    """Otherwise a failed update is completely silent: nothing changed."""
    import mixar.modules.common.updates.core.install_flow as install_flow
    import mixar.modules.common.updates.core.update_checker as update_checker

    monkeypatch.setattr(
        install_flow, "read_previous_result",
        lambda: {"version": "3.4.0", "stage": "install", "exit": "1602"},
    )
    monkeypatch.setattr(update_checker, "get_runtime_version", lambda: "3.3.6")

    toasts.report_previous_update_result()

    item = _toast()
    assert item.title == "Update was not installed"
    assert "cancelled" in item.body
    assert [a.label for a in item.actions] == ["Download"]


def test_successful_install_confirms_the_new_version(monkeypatch):
    import mixar.modules.common.updates.core.install_flow as install_flow
    import mixar.modules.common.updates.core.update_checker as update_checker

    monkeypatch.setattr(
        install_flow, "read_previous_result",
        lambda: {"version": "3.4.0", "stage": "install", "exit": "0"},
    )
    monkeypatch.setattr(update_checker, "get_runtime_version", lambda: "3.4.0")

    toasts.report_previous_update_result()

    assert _toast().title == "Updated to Mixar 3.4.0"


def test_install_that_reported_success_but_did_not_take_effect_is_flagged(monkeypatch):
    """The signal that a Windows upgrade landed beside the old build."""
    import mixar.modules.common.updates.core.install_flow as install_flow
    import mixar.modules.common.updates.core.update_checker as update_checker

    monkeypatch.setattr(
        install_flow, "read_previous_result",
        lambda: {"version": "3.4.0", "stage": "install", "exit": "0"},
    )
    monkeypatch.setattr(update_checker, "get_runtime_version", lambda: "3.3.6")

    toasts.report_previous_update_result()

    assert _toast().title == "Update didn't take effect"


def test_nothing_is_reported_when_no_update_ran(monkeypatch):
    import mixar.modules.common.updates.core.install_flow as install_flow

    monkeypatch.setattr(install_flow, "read_previous_result", lambda: None)

    toasts.report_previous_update_result()

    assert get_notification_store().contains(UPDATE_NOTIFICATION_ID) is False


# ---------------------------------------------------------------------------
# Operator wiring (bpy is a mock, so the source is the contract)
# ---------------------------------------------------------------------------


def _operator_classes():
    tree = ast.parse(OPERATORS_SRC.read_text(encoding="utf-8"))
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    }


def _bl_idname(node):
    for stmt in node.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if getattr(target, "id", "") == "bl_idname":
                    return stmt.value.value
    return ""


def test_restart_and_cancel_operators_are_registered():
    classes = _operator_classes()
    idnames = {_bl_idname(node) for node in classes.values()}

    assert "mixar.restart_to_update" in idnames
    assert "mixar.cancel_update_download" in idnames

    registered = OPERATORS_SRC.read_text(encoding="utf-8")
    assert "MIXAR_OT_restart_to_update," in registered
    assert "MIXAR_OT_cancel_update_download," in registered


def test_restart_operator_confirms_before_quitting():
    """No unconfirmed quit: unsaved work is the user's, not ours to drop."""
    source = OPERATORS_SRC.read_text(encoding="utf-8")
    restart = source[source.index("class MIXAR_OT_restart_to_update"):
                     source.index("class MIXAR_OT_cancel_update_download")]

    assert "invoke_props_dialog" in restart
    assert "save_mainfile" in restart
    # The quit itself only happens through the flow, after apply succeeds.
    assert "quit_blender" not in restart
    assert "apply_and_restart" in restart


def test_failed_save_cancels_the_update():
    source = OPERATORS_SRC.read_text(encoding="utf-8")
    restart = source[source.index("class MIXAR_OT_restart_to_update"):
                     source.index("class MIXAR_OT_cancel_update_download")]
    save_block = restart[restart.index("save_mainfile"):]

    assert 'return {"CANCELLED"}' in save_block[:400]


# ---------------------------------------------------------------------------
# Telemetry — content-free by construction
# ---------------------------------------------------------------------------


def test_update_events_carry_versions_and_outcomes_only():
    """Exact key sets, so a future addition fails here rather than shipping."""
    from unittest.mock import patch

    from mixar.modules.common.analytics import update_events

    with patch.object(update_events, "capture") as captured:
        update_events.capture_update_download("3.4.0", "ready")
        update_events.capture_update_started("3.4.0", True)
        update_events.capture_update_result("3.4.0", "failed", "install")

    names = [call.args[0] for call in captured.call_args_list]
    assert names == [
        "update.download_finished",
        "update.install_started",
        "update.install_result",
    ]

    payloads = [call.args[1] for call in captured.call_args_list]
    assert set(payloads[0]) == {"target_version", "outcome"}
    assert set(payloads[1]) == {"target_version", "signature_verified"}
    assert set(payloads[2]) == {"target_version", "outcome", "stage"}


def test_result_telemetry_distinguishes_an_update_that_did_not_apply(monkeypatch):
    from unittest.mock import patch

    import mixar.modules.common.updates.core.install_flow as install_flow
    import mixar.modules.common.updates.core.update_checker as update_checker
    from mixar.modules.common.analytics import update_events

    monkeypatch.setattr(
        install_flow, "read_previous_result",
        lambda: {"version": "3.4.0", "stage": "install", "exit": "0"},
    )
    monkeypatch.setattr(update_checker, "get_runtime_version", lambda: "3.3.6")

    with patch.object(update_events, "capture") as captured:
        toasts.report_previous_update_result()

    assert captured.call_args_list[0].args[1]["outcome"] == "no_effect"


def test_forced_download_toast_offers_no_cancel():
    """Cancelling the download would otherwise be a back door out of a
    toast that is deliberately impossible to dismiss."""
    state = get_update_state()
    info = _info(force_update=True)
    state.set_available(info)
    state.set_downloading()
    state.set_install_requested(True)

    toasts.push_update_available_toast(info)

    item = _toast()
    assert item.actions == []
    assert item.dismissible is False


def test_cancel_operator_refuses_a_forced_update():
    source = OPERATORS_SRC.read_text(encoding="utf-8")
    cancel = source[source.index("class MIXAR_OT_cancel_update_download"):
                    source.index("class MIXAR_OT_open_downloads_page")]

    assert "is_forced" in cancel
    assert cancel.index("is_forced(info)") < cancel.index("cancel_download()")


# ---------------------------------------------------------------------------
# Toast click dispatch — the UAT regression of 2026-08-21
# ---------------------------------------------------------------------------

TOAST_DISPATCH_SRC = (
    SCRIPTS / "mixar" / "modules" / "common" / "notifications" / "ui"
    / "toast_dismiss_op.py"
)


def test_toast_buttons_dispatch_with_invoke_not_exec():
    """Toast clicks ran operators with EXEC_DEFAULT, which skips invoke() —
    so Restart & Update's routing and confirm dialog never ran and the
    click errored with "The update isn't ready yet". INVOKE_DEFAULT falls
    back to execute() for the invoke-less operators, so nothing else moves."""
    source = TOAST_DISPATCH_SRC.read_text(encoding="utf-8")
    dispatch = source[source.index("def _invoke_operator"):]
    dispatch = dispatch[:dispatch.index("\ndef ")]

    assert "'INVOKE_DEFAULT'" in dispatch
    # Timer callbacks carry no window; a dialog needs one borrowed in.
    assert "temp_override" in dispatch
    # EXEC survives only as the no-window fallback.
    assert dispatch.count("'EXEC_DEFAULT'") == 1


def test_restart_execute_routes_when_the_dialog_was_skipped():
    """An EXEC-dispatched click must behave like invoke(): start/await the
    download or fall back to the browser — never error on a not-ready state,
    and never quit over unsaveable work."""
    source = OPERATORS_SRC.read_text(encoding="utf-8")
    restart = source[source.index("class MIXAR_OT_restart_to_update"):
                     source.index("class MIXAR_OT_cancel_update_download")]
    execute = restart[restart.index("def execute"):]

    assert "_confirmed_via_dialog" in execute
    assert "_route(context)" in execute
    assert "Save your work first" in execute


def test_failed_download_toast_says_why():
    """A failed background download used to fall back to the Download button
    with no explanation — indistinguishable from a browser-only release."""
    state = get_update_state()
    state.set_available(_info())
    state.set_install_failed("Download failed (HTTP 404)")

    toasts.push_update_available_toast(_info())

    item = _toast()
    assert "Download failed (HTTP 404)" in item.body
    assert [a.label for a in item.actions] == ["Download"]


# ---------------------------------------------------------------------------
# Download progress UI + aborted-quit recovery (Windows UAT round 2)
# ---------------------------------------------------------------------------


def test_background_download_keeps_its_progress_out_of_the_toast():
    """Staging is background work until the user asks to wait on it.

    The percentage lives on the topbar badge ("Downloading 45%") while the
    download is unrequested; putting it in the toast turns an announcement
    the user has read into a progress bar they did not ask for.
    """
    state = get_update_state()
    state.set_available(_info())
    state.set_downloading()
    state.set_download_progress(100 * 1024 * 1024, 400 * 1024 * 1024)

    toasts.push_update_available_toast(_info())

    item = _toast()
    assert "Downloading" not in item.body
    assert "25%" not in item.body
    assert "Version 3.4.0 is available." in item.body
    # Still the normal toast: the user can restart (queues the intent) or dismiss.
    assert _labels() == ["Restart & Update"]


def test_requested_download_shows_live_progress():
    """Once the user pressed Restart & Update they are waiting on it.

    A 400 MB download with no moving number looks stalled, so this is the
    toast that carries the percentage — and it offers Cancel, not Restart.
    """
    state = get_update_state()
    state.set_available(_info())
    state.set_downloading()
    state.set_install_requested(True)
    state.set_download_progress(100 * 1024 * 1024, 400 * 1024 * 1024)

    toasts.push_update_available_toast(_info())

    item = _toast()
    assert "Downloading Mixar 3.4.0" == item.title
    assert "25%" in item.body
    assert "400 MB" in item.body
    assert _labels() == ["Cancel"]


def test_badge_shows_download_percentage():
    from mixar.modules.common.updates.ui.topbar_badge import badge_label

    state = get_update_state()
    state.set_available(_info())

    state.set_downloading()
    assert badge_label(state) == "Downloading…"
    state.set_download_progress(200 * 1024 * 1024, 400 * 1024 * 1024)
    assert badge_label(state) == "Downloading 50%"

    state.set_ready("/tmp/Mixar-3.4.0.msi", True)
    assert badge_label(state) == "Restart to Update"
    state.set_installing()
    assert badge_label(state) == "Updating…"


def test_aborted_quit_returns_to_ready_and_says_so():
    """Quit scheduled, Mixar still running: kill the helper, keep the staged
    installer, and tell the user to click again — never a silent stall with
    a five-minute helper still waiting to install behind their back."""
    from mixar.modules.common.updates.core import install_flow

    state = get_update_state()
    state.set_available(_info())
    state.set_ready("/tmp/Mixar-3.4.0.msi", True)
    state.set_installing()
    install_flow._helper_proc = None

    install_flow._abort_pending_install()

    from mixar.modules.common.updates.constants import InstallState

    assert state.install_state is InstallState.READY
    assert state.installer_path == "/tmp/Mixar-3.4.0.msi"
    item = _toast()
    assert item.title == "Update paused"
    assert "didn't close" in item.body
    assert [a.label for a in item.actions] == ["Restart & Update"]


def test_quit_watchdog_only_fires_while_installing():
    from mixar.modules.common.updates.core import install_flow

    state = get_update_state()
    state.set_available(_info())
    state.set_ready("/tmp/Mixar-3.4.0.msi", True)

    assert install_flow._quit_watchdog() is None

    from mixar.modules.common.updates.constants import InstallState

    assert state.install_state is InstallState.READY
    assert not get_notification_store().contains(UPDATE_NOTIFICATION_ID)


# ============================================================================
# The one announcement that survives dismissal
#
# "Downloaded, one restart away" is new and actionable, so it re-opens the
# toast even if the availability toast was dismissed — but exactly once per
# version. After that the badge ("Restart to Update") carries it.
# ============================================================================


def _install_fake_announcements(monkeypatch, initial=""):
    from mixar.modules.common.updates.core import update_checker

    box = {"value": initial}

    def _get(version):
        recorded, _, stage = box["value"].partition("=")
        return stage if recorded == version and version else ""

    def _set(version, stage):
        box["value"] = f"{version}={stage}"

    monkeypatch.setattr(update_checker, "get_announced_stage", _get)
    monkeypatch.setattr(update_checker, "set_announced_stage", _set)
    return box


def test_ready_reopens_a_dismissed_toast_once(monkeypatch):
    from mixar.modules.common.updates.core import install_flow

    box = _install_fake_announcements(monkeypatch, initial="3.4.0=available")
    state = get_update_state()
    info = _info()
    state.set_available(info)
    state.set_ready("/tmp/Mixar-3.4.0.msi", True)
    get_notification_store().clear_all()  # the user dismissed it

    install_flow._announce_ready(state)

    assert _toast().title == "Mixar Update Ready"
    assert box["value"] == "3.4.0=ready"

    # Second pass (a later check, or a re-verified staged installer) must
    # not interrupt again.
    get_notification_store().clear_all()
    install_flow._announce_ready(state)
    assert all(
        i.id != UPDATE_NOTIFICATION_ID
        for i in get_notification_store().get_visible()
    )


def test_ready_announcement_is_skipped_while_still_downloading(monkeypatch):
    from mixar.modules.common.updates.core import install_flow

    box = _install_fake_announcements(monkeypatch, initial="3.4.0=available")
    state = get_update_state()
    info = _info()
    state.set_available(info)
    state.set_downloading()
    get_notification_store().clear_all()

    install_flow._announce_ready(state)

    assert box["value"] == "3.4.0=available"
    assert all(
        i.id != UPDATE_NOTIFICATION_ID
        for i in get_notification_store().get_visible()
    )


def test_progress_tick_only_repushes_the_toast_the_user_waits_on(monkeypatch):
    """A static toast must not be replaced once a second.

    The badge needs the redraw either way, but re-pushing a notification
    whose text has not changed churns the store under a user who may be
    reaching for its button.
    """
    from mixar.modules.common.updates.core import install_flow

    calls = {"toast": 0, "badge": 0}
    monkeypatch.setattr(
        install_flow, "_refresh_ui", lambda: calls.__setitem__("toast", calls["toast"] + 1),
    )
    monkeypatch.setattr(
        install_flow, "_redraw_badge", lambda: calls.__setitem__("badge", calls["badge"] + 1),
    )

    state = get_update_state()
    state.set_available(_info())
    state.set_downloading()

    install_flow._progress_tick()
    assert calls == {"toast": 0, "badge": 1}

    state.set_install_requested(True)
    install_flow._progress_tick()
    assert calls == {"toast": 1, "badge": 1}


def test_progress_tick_stops_when_the_download_ends(monkeypatch):
    from mixar.modules.common.updates.core import install_flow

    state = get_update_state()
    state.set_available(_info())
    state.set_ready("/tmp/Mixar-3.4.0.msi", True)

    assert install_flow._progress_tick() is None


# ============================================================================
# The timer-invoked restart prompt borrows a window
#
# _after_download runs inside a bpy.app.timers callback, whose context
# usually carries no window — and INVOKE_DEFAULT opens the unsaved-work
# confirmation, which needs one. The same PR fixed this for toast clicks;
# the restart prompt must get the same treatment or the invoke silently
# fails after install_requested has already been consumed.
# ============================================================================

INSTALL_FLOW_SRC = (
    SCRIPTS / "mixar" / "modules" / "common" / "updates" / "core" / "install_flow.py"
)


def test_after_download_invokes_the_restart_prompt_with_a_window():
    source = INSTALL_FLOW_SRC.read_text(encoding="utf-8")
    after = source[source.index("def _after_download"):]
    after = after[:after.index("\n\n\n")]

    assert 'bpy.ops.mixar.restart_to_update("INVOKE_DEFAULT")' in after
    # Timer contexts carry no window; a dialog needs one borrowed in.
    assert "temp_override" in after
    assert "window_manager.windows" in after
    # The request is consumed BEFORE the invoke, so a failed invoke can be
    # retried from the toast/badge instead of auto-firing on every tick.
    assert after.index("set_install_requested(False)") < after.index(
        "restart_to_update"
    )
