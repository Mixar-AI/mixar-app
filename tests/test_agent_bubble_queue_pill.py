# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent Bubble status pill reporting unified-queue activity.

The pill previously showed "Idle" whenever no agent turn was running, which
is what the agent looks like moments after it enqueues a multi-minute paid
generation — nothing on screen said work was outstanding or where to check.

The precedence rules pinned here are the point: queue activity is orthogonal
to the agent turn, so it is surfaced ONLY in the branch that used to say
"Idle". Every state above it — disconnected, reconnecting, running,
awaiting input — is something the user must act on and must never be masked
by background work.

Also covers the redraw plumbing: the bubble and its minimised pill live in
their own wmWindows, so a queue change that tags only VIEW_3D/MIXIE areas
leaves the pill painting a stale label.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# pill_icons does `import bpy.utils.previews`, which the root conftest's stub
# hierarchy doesn't reach.
sys.modules.setdefault("bpy.utils.previews", MagicMock(name="bpy.utils.previews"))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.agent_bubble.ui import header as HDR
from mixar.modules.common.job_queue.core import model_io as MIO


def _scene(state):
    return SimpleNamespace(mixie_chat_state=state)


def _status(monkeypatch, state, *, jobs=0, transport_down=False):
    monkeypatch.setattr(HDR, "_transport_down", lambda: transport_down)
    monkeypatch.setattr(HDR, "_active_queue_jobs", lambda: jobs)
    return HDR._get_status(_scene(state))


# ---------------------------------------------------------------------------
# The queue branch
# ---------------------------------------------------------------------------


def test_idle_with_no_queue_work_still_reads_idle(monkeypatch):
    assert _status(monkeypatch, "IDLE") == ("Idle", "grey", 'RECORD_OFF')


def test_idle_with_one_job_reports_generating(monkeypatch):
    label, colour, _ = _status(monkeypatch, "IDLE", jobs=1)
    assert label == "Generating"
    # "green" is what makes _draw_status append the animated dot suffix.
    assert colour == "green"


def test_idle_with_several_jobs_reports_the_count(monkeypatch):
    label, colour, _ = _status(monkeypatch, "IDLE", jobs=3)
    assert label == "Generating 3"
    assert colour == "green"


def test_queue_label_width_is_bounded(monkeypatch):
    """The pill window is a FIXED 148 px (AGENT_BUBBLE_PILL_WIDTH), so the
    label must not grow with the job count — a fan-out of 40 retopology jobs
    would otherwise clip the text mid-word."""
    assert HDR._queue_label(40) == "Generating 9+"

    # Widest producible label: the cap plus the 3-char animated suffix.
    widest = max(
        len(HDR._queue_label(n)) for n in (1, 2, HDR._QUEUE_COUNT_CAP, 999)
    ) + 3
    assert widest <= 16


# ---------------------------------------------------------------------------
# Precedence — background work must not mask states the user must act on
# ---------------------------------------------------------------------------


def test_running_turn_outranks_queue_work(monkeypatch):
    for state in ("BUSY", "MODIFYING"):
        label, colour, _ = _status(monkeypatch, state, jobs=2)
        assert (label, colour) == ("Running", "green")


def test_awaiting_input_outranks_queue_work(monkeypatch):
    label, _, _ = _status(monkeypatch, "AWAITING_INPUT", jobs=2)
    assert label == "Awaiting Input"


def test_offline_outranks_queue_work(monkeypatch):
    label, _, _ = _status(monkeypatch, "OFFLINE", jobs=2)
    assert label == "Disconnected"


def test_connecting_outranks_queue_work(monkeypatch):
    label, _, _ = _status(monkeypatch, "CONNECTING", jobs=2)
    assert label == "Connecting"


def test_reconnecting_outranks_queue_work(monkeypatch):
    label, _, _ = _status(monkeypatch, "IDLE", jobs=2, transport_down=True)
    assert label == "Reconnecting"


# ---------------------------------------------------------------------------
# Draw safety
# ---------------------------------------------------------------------------


def test_active_queue_jobs_never_raises_into_a_draw(monkeypatch):
    """A header draw that raises leaves the bubble unpainted."""
    import builtins

    real_import = builtins.__import__

    def _boom(name, *args, **kwargs):
        if "queue_manager" in name:
            raise ImportError("queue module unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _boom)
    assert HDR._active_queue_jobs() == 0


# ---------------------------------------------------------------------------
# Redraw surfaces
# ---------------------------------------------------------------------------


def _fake_area(area_type, region_count=2):
    return SimpleNamespace(
        type=area_type,
        tagged=False,
        regions=[SimpleNamespace(tagged=False) for _ in range(region_count)],
    )


def _wire(area):
    def tag():
        area.tagged = True
    area.tag_redraw = tag
    for region in area.regions:
        def tag_region(r=region):
            r.tagged = True
        region.tag_redraw = tag_region
    return area


def test_bubble_is_a_queue_redraw_surface():
    assert 'AGENT_BUBBLE' in MIO.QUEUE_SURFACE_AREA_TYPES


def test_tag_redraw_reaches_bubble_regions_and_skips_other_editors(monkeypatch):
    bubble = _wire(_fake_area('AGENT_BUBBLE'))
    viewport = _wire(_fake_area('VIEW_3D'))
    outliner = _wire(_fake_area('OUTLINER'))

    fake_bpy = SimpleNamespace(
        context=SimpleNamespace(
            window_manager=SimpleNamespace(
                windows=[
                    SimpleNamespace(
                        screen=SimpleNamespace(
                            areas=[bubble, viewport, outliner],
                        ),
                    ),
                ],
            ),
        ),
    )
    monkeypatch.setattr(MIO, "bpy", fake_bpy)

    MIO.tag_redraw_queue_surfaces()

    assert bubble.tagged and viewport.tagged
    assert not outliner.tagged
    # The pill's label lives in the header REGION; tagging the area alone
    # left it static (same finding as the chat loader animation).
    assert all(r.tagged for r in bubble.regions)
    assert not any(r.tagged for r in viewport.regions)
