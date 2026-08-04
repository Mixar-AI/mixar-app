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
from mixar.modules.common.job_queue.core.queue_manager import QueueActivity


def _scene(state):
    return SimpleNamespace(mixie_chat_state=state)


def _activity(count, label="", elapsed=84.0):
    """A queue summary whose oldest job started ``elapsed`` seconds ago."""
    if not count:
        return None
    import time
    return QueueActivity(count, label, time.monotonic() - elapsed)


def _status(monkeypatch, state, *, jobs=0, label="", elapsed=84.0,
            transport_down=False):
    monkeypatch.setattr(HDR, "_transport_down", lambda: transport_down)
    monkeypatch.setattr(
        HDR, "_queue_activity", lambda: _activity(jobs, label, elapsed),
    )
    return HDR._get_status(_scene(state))


# ---------------------------------------------------------------------------
# The queue branch
# ---------------------------------------------------------------------------


def test_idle_with_no_queue_work_still_reads_idle(monkeypatch):
    status = _status(monkeypatch, "IDLE")
    assert (status.label, status.colour) == ("Idle", "grey")
    assert not status.animate


def test_one_job_is_named_and_clocked(monkeypatch):
    status = _status(monkeypatch, "IDLE", jobs=1, label="Image Gen")
    assert status.label == "Image Gen 1:24"
    assert status.colour == "green"


def test_several_jobs_report_a_count_not_a_name(monkeypatch):
    """Naming one of three jobs would misrepresent the other two."""
    status = _status(monkeypatch, "IDLE", jobs=3, label="Image Gen")
    assert status.label == "3 jobs 1:24"


def test_unknown_capability_falls_back_to_generic_wording(monkeypatch):
    """An empty label means the catalog couldn't answer — never leak a raw
    service key like "mesh_segment" into the pill."""
    status = _status(monkeypatch, "IDLE", jobs=1, label="")
    assert status.label == "Generating 1:24"


def test_long_capability_name_drops_to_generic_rather_than_clipping(monkeypatch):
    """"Mesh Segmentation 1:24" is 22 chars in a 148 px window."""
    status = _status(monkeypatch, "IDLE", jobs=1, label="Mesh Segmentation")
    assert status.label == "Generating 1:24"


def test_clock_is_the_animation_so_dots_are_off(monkeypatch):
    """A ticking clock and a dot pulse are two competing animations."""
    queue_status = _status(monkeypatch, "IDLE", jobs=2)
    assert not queue_status.animate

    agent_status = _status(monkeypatch, "BUSY", jobs=2)
    assert agent_status.animate


def test_count_is_capped(monkeypatch):
    status = _status(monkeypatch, "IDLE", jobs=40)
    assert status.label == "9+ jobs 1:24"


def test_hour_long_job_keeps_the_label_narrow(monkeypatch):
    """h:mm:ss is three characters wider than m:ss and would clip."""
    status = _status(monkeypatch, "IDLE", jobs=1, label="Image Gen",
                     elapsed=7300.0)
    assert status.label == "Image Gen 2h+"


def test_every_producible_label_fits_the_pill(monkeypatch):
    """The pill window is a FIXED 148 px (AGENT_BUBBLE_PILL_WIDTH); Blender
    clips overflow mid-word rather than shrinking the text."""
    worst = [
        _status(monkeypatch, "IDLE", jobs=n, label=lbl, elapsed=sec).label
        for n in (1, 2, 9, 40)
        for lbl in ("", "Image Gen", "Mesh Segmentation", "UV Unwrapping")
        for sec in (0.0, 84.0, 3599.0, 7300.0)
    ]
    assert max(len(text) for text in worst) <= HDR._QUEUE_TEXT_BUDGET


# ---------------------------------------------------------------------------
# Precedence — background work must not mask states the user must act on
# ---------------------------------------------------------------------------


def test_running_turn_outranks_queue_work(monkeypatch):
    for state in ("BUSY", "MODIFYING"):
        status = _status(monkeypatch, state, jobs=2)
        assert (status.label, status.colour) == ("Running", "green")


def test_awaiting_input_outranks_queue_work(monkeypatch):
    assert _status(monkeypatch, "AWAITING_INPUT", jobs=2).label == "Awaiting Input"


def test_offline_outranks_queue_work(monkeypatch):
    assert _status(monkeypatch, "OFFLINE", jobs=2).label == "Disconnected"


def test_connecting_outranks_queue_work(monkeypatch):
    assert _status(monkeypatch, "CONNECTING", jobs=2).label == "Connecting"


def test_reconnecting_outranks_queue_work(monkeypatch):
    status = _status(monkeypatch, "IDLE", jobs=2, transport_down=True)
    assert status.label == "Reconnecting"


# ---------------------------------------------------------------------------
# Draw safety
# ---------------------------------------------------------------------------


def test_queue_activity_never_raises_into_a_draw(monkeypatch):
    """A header draw that raises leaves the bubble unpainted."""
    import builtins

    real_import = builtins.__import__

    def _boom(name, *args, **kwargs):
        if "queue_manager" in name:
            raise ImportError("queue module unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _boom)
    assert HDR._queue_activity() is None


def test_queue_clock_survives_a_missing_labels_module(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _boom(name, *args, **kwargs):
        if name.endswith("labels"):
            raise ImportError("labels module unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _boom)
    assert HDR._queue_clock(1.0) == ""


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
