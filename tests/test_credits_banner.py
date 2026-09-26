# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The out-of-credits banner replaces every out-of-credits toast.

Pins: one banner per burst of credit failures, no reopen on a sync replay of
the same push, no credit toast from the job queue or the mask tool, and the
native operator wired where Python expects it.
"""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.notifications import credits_banner as CB  # noqa: E402
from mixar.modules.common.notifications import credit_upgrade as CU  # noqa: E402
from mixar.modules.common.job_queue.core import error_helpers as EH  # noqa: E402
from mixar.modules.common.api.exceptions import InsufficientCreditsError  # noqa: E402
from mixar.modules.moodboard.core import mask_tool_feedback as feedback  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "src/scripts/mixar/modules"
EDITORS = ROOT / "src/source/blender/editors"


@pytest.fixture
def banner(monkeypatch):
    """Capture scheduled opens instead of touching a window."""
    scheduled = []
    clock = SimpleNamespace(now=1000.0)
    fake_bpy = SimpleNamespace(
        app=SimpleNamespace(
            background=False,
            timers=SimpleNamespace(register=lambda fn, first_interval=0: scheduled.append(fn)),
        ),
    )
    monkeypatch.setattr(CB, "bpy", fake_bpy)
    monkeypatch.setattr(CB, "time", SimpleNamespace(monotonic=lambda: clock.now))
    CB.reset_state()

    def run_pending():
        # What the main-thread timer would do, minus the window: consume the
        # pending request and stamp the open.
        with CB._lock:
            CB._pending_trigger = None
            CB._last_activity = clock.now
        scheduled.clear()

    yield SimpleNamespace(scheduled=scheduled, clock=clock, run_pending=run_pending)
    CB.reset_state()


def test_a_burst_of_credit_failures_opens_one_banner(banner):
    CB.request_credits_banner("http_402")
    CB.request_credits_banner("job")  # same failure, second reporter
    assert len(banner.scheduled) == 1
    banner.run_pending()

    banner.clock.now += 5.0
    CB.request_credits_banner("job")  # the rest of the batch fails
    assert banner.scheduled == []


def test_a_new_failure_after_the_cooldown_opens_it_again(banner):
    CB.request_credits_banner("http_402")
    banner.run_pending()
    CB.note_banner_closed()
    banner.clock.now += CB.CREDITS_BANNER_BURST_COOLDOWN_S + 1.0
    CB.request_credits_banner("http_402")
    assert len(banner.scheduled) == 1


def test_a_repeated_push_id_never_reopens(banner):
    CB.request_credits_banner("push", push_id="n-1")
    banner.run_pending()
    banner.clock.now += 3600.0
    CB.request_credits_banner("push", push_id="n-1")
    assert banner.scheduled == []
    CB.request_credits_banner("push", push_id="n-2")
    assert len(banner.scheduled) == 1


def test_headless_workers_never_schedule_a_banner(banner, monkeypatch):
    monkeypatch.setattr(CB.bpy.app, "background", True)
    CB.request_credits_banner("http_402")
    assert banner.scheduled == []


def test_backend_push_opens_the_banner_instead_of_a_toast(monkeypatch):
    calls = []
    monkeypatch.setattr(CB, "request_credits_banner", lambda *a, **k: calls.append((a, k)))
    CU.push_credit_upgrade({"id": "n-9", "action_url": "https://pay.example/plan"})
    assert calls == [(("push",), {"action_url": "https://pay.example/plan", "push_id": "n-9"})]
    assert CU.get_pending_upgrade_url() == "https://pay.example/plan"
    assert "get_notification_store" not in (MODULES / "common/notifications/credit_upgrade.py").read_text()


def test_the_queue_recognises_its_credit_failures_by_the_shared_message():
    error = InsufficientCreditsError(message="Payment Required", status_code=402)
    assert EH.classify_error(error) == EH.OUT_OF_CREDITS_MESSAGE
    source = (MODULES / "common/job_queue/core/queue_manager.py").read_text()
    method = source[source.index("def _notify_failure_toasts"):]
    method = method[:method.index("\n    def ", 1)]
    # The banner check comes before the toast push, and skips it.
    assert method.index("OUT_OF_CREDITS_MESSAGE") < method.index("get_notification_store().push")
    assert "continue" in method[method.index("OUT_OF_CREDITS_MESSAGE"):method.index("try:")]


def test_mask_tool_credit_failure_opens_the_banner_not_a_toast(monkeypatch):
    toasts, banners = [], []
    monkeypatch.setattr(feedback, "toast", lambda kind, title, body="": toasts.append(title))
    monkeypatch.setattr(CB, "request_credits_banner", lambda trigger, **k: banners.append(trigger))
    feedback.toast_failure("HTTP 402 Payment Required")
    assert banners == ["mask_tool"] and toasts == []
    feedback.toast_failure("boom")
    assert toasts == [feedback.FAILED_TITLE]


def test_every_rest_402_requests_the_banner():
    source = (MODULES / "common/api/client.py").read_text()
    branch = source[source.index("elif status == 402:"):source.index("elif status == 403:")]
    assert 'request_credits_banner("http_402"' in branch


def test_chat_fallback_requests_the_banner_and_keeps_its_bubble():
    source = (MODULES / "space_mixie_chat/core/credits_notice.py").read_text()
    fn = source[source.index("def add_credit_upgrade_chat_message"):]
    assert 'request_credits_banner("chat"' in fn
    assert "if request_banner:" in fn
    assert "CREDITS_BUBBLE_PREFIX" in fn


def test_banner_actions_cover_every_native_choice():
    """The C++ side sends these names; Python must accept every one."""
    native = (EDITORS / "interface/mixar/credits_banner.cc").read_text()
    ops_path = MODULES / "common/notifications/ui/operators/credits_banner_ops.py"
    tree = ast.parse(ops_path.read_text())
    actions = next(
        ast.literal_eval(node.value) for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", None) == "BANNER_ACTIONS" for t in node.targets)
    )
    for name in actions:
        assert f'return "{name}";' in native
    assert '"MIXAR_OT_credits_banner_action"' in native
    assert 'bl_idname = "mixar.credits_banner_action"' in ops_path.read_text()


def test_creator_program_link_matches_the_help_menu():
    from mixar.modules.common.notifications import constants as C

    help_menu = (ROOT / "src/scripts/startup/bl_ui/space_topbar.py").read_text()
    assert C.CREDITS_BANNER_CREATOR_URL in help_menu
    assert C.CREDITS_BANNER_REFERRAL_URL == "https://www.mixar.app/app/referrals"


def test_native_operator_is_registered_and_built():
    topbar = (EDITORS / "space_topbar/space_topbar.cc").read_text()
    body = topbar[topbar.index("static void topbar_operatortypes()"):]
    assert "ED_mixar_credits_banner_register();" in body[:body.index("}")]
    cmake = (EDITORS / "interface/CMakeLists.txt").read_text()
    for name in ("credits_banner.cc", "credits_banner_draw.cc", "credits_banner.hh"):
        assert f"mixar/{name}" in cmake


def test_banner_art_ships_small():
    art = MODULES / "common/notifications/assets/credits_banner.webp"
    assert art.is_file()
    # Everything under src/scripts ships in the installer.
    assert art.stat().st_size < 400_000
    assert CB.banner_image_path().endswith("assets/credits_banner.webp")


def test_banner_telemetry_is_one_allowlisted_enum(monkeypatch):
    from mixar.modules.common.analytics import credits_events as E

    sent = []
    monkeypatch.setattr(E, "capture", lambda event, props, context=None: sent.append((event, props)))
    E.capture_credits_banner_shown("http_402")
    E.capture_credits_banner_shown("a prompt the user typed")
    E.capture_credits_banner_action("UPGRADE")
    E.capture_credits_banner_action("/Users/someone/file.blend")
    assert sent == [
        ("credits.banner_shown", {"trigger": "http_402"}),
        ("credits.banner_shown", {"trigger": "other"}),
        ("credits.banner_action", {"action": "upgrade"}),
        ("credits.banner_action", {"action": "dismiss"}),
    ]
    # Every trigger the code sends is allowlisted.
    for path in MODULES.rglob("*.py"):
        text = path.read_text(errors="ignore")
        for trigger in ("push", "http_402", "chat", "job", "mask_tool", "manual"):
            if f'request_credits_banner("{trigger}"' in text:
                assert trigger in E.BANNER_TRIGGERS


def test_the_push_chat_bubble_does_not_request_a_second_banner():
    """A reconnect replay is deduped by push id; the chat bubble the same push
    adds must not reopen the banner under its own trigger."""
    source = (MODULES / "space_mixie_chat/core/connection_manager.py").read_text()
    branch = source[source.index('if notif_type == "credit_upgrade":'):]
    branch = branch[:branch.index("return\n")]
    assert "request_banner=False" in branch
