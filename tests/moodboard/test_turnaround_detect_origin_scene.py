# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Detect Views results land in the tab that started the detection.

Production defect (4.2.3, session 0eb90899): an agent ran detect-views in its
tab, the user opened another tab during the ~30 s request, and the response
callback wrote the crops, the group and the cleared in-flight flag into
``bpy.context.scene`` — the tab now shown. The agent's tab never saw the
group and kept ``mixie_detect_views_running`` set, so its poll timed out and
every retry failed ``poll()``; the character was built from one view.
"""

from types import SimpleNamespace

import pytest

from mixar.modules.common.api import services
from mixar.modules.common.job_queue.core import queue_download
from mixar.modules.common.utils import image_utils
from mixar.modules.moodboard.core import turnaround_detect


def _tab(name, session, pointer=None):
    tab = SimpleNamespace(
        name=name, mixie_session_id=session,
        mixie_detect_views_running=False, mixie_detect_views_status="",
    )
    if pointer is not None:
        tab.as_pointer = lambda: pointer
    return tab


class _Scenes:
    """``bpy.data.scenes`` over the rig's open tabs (keyed by session)."""

    def __init__(self, open_tabs):
        self._open_tabs = open_tabs

    def get(self, name):
        return next((t for t in self if t.name == name), None)

    def __iter__(self):
        return iter(list(self._open_tabs.values()))


class _Service:
    def __init__(self):
        self.calls = []

    def detect_views_async(self, image_bytes, **kwargs):
        self.calls.append(kwargs)


@pytest.fixture
def rig(monkeypatch):
    """Two open tabs, a captured detect request, synchronous threads/timers."""
    agent_tab = _tab("Using This Multi View", "session-agent", pointer=101)
    other_tab = _tab("4 Images Of The Same", "session-other", pointer=202)
    open_tabs = {t.mixie_session_id: t for t in (agent_tab, other_tab)}
    context = SimpleNamespace(scene=agent_tab)
    fake_bpy = SimpleNamespace(
        context=context,
        data=SimpleNamespace(scenes=_Scenes(open_tabs)),
        app=SimpleNamespace(timers=SimpleNamespace(
            register=lambda fn, first_interval=0.0: fn())),
    )
    service = _Service()
    added = []

    def resolve(scene_name, session_id=""):
        tab = open_tabs.get(session_id)
        return tab if tab is not None and tab.name == scene_name else None

    class _InlineThread:
        def __init__(self, target, daemon=None):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(turnaround_detect, "bpy", fake_bpy)
    monkeypatch.setattr(turnaround_detect.threading, "Thread", _InlineThread)
    monkeypatch.setattr(services, "get_model_3d_service", lambda: service)
    monkeypatch.setattr(image_utils, "compress_for_service", lambda *a: b"jpeg")
    monkeypatch.setattr(image_utils, "download_image_to_tempfile",
                        lambda url: (f"/tmp/{url}.png", None))
    monkeypatch.setattr(queue_download, "resolve_job_scene", resolve)
    monkeypatch.setattr(
        turnaround_detect, "_add_panels_to_moodboard",
        lambda scene, source, base, downloaded: (
            added.append(scene) or ("turnaround_x", len(downloaded) - 1)))
    monkeypatch.setattr(turnaround_detect, "_discard", lambda downloaded: None)

    return SimpleNamespace(
        agent_tab=agent_tab, other_tab=other_tab, open_tabs=open_tabs,
        context=context, service=service, added=added)


def _start(rig, events):
    # What the operator does before the request goes out.
    rig.agent_tab.mixie_detect_views_running = True
    rig.agent_tab.mixie_detect_views_status = "Detecting views..."
    turnaround_detect.detect_views(
        SimpleNamespace(name="sheet"),
        on_done=lambda scene, gid, count: events.append(("done", scene, count)),
        on_error=lambda scene, msg: events.append(("error", scene, msg)),
        on_not_turnaround=lambda scene: events.append(("single", scene)),
        scene=rig.agent_tab,
    )
    # The user opens another tab while the request is in flight.
    rig.context.scene = rig.other_tab
    return rig.service.calls[-1]


def _turnaround_response():
    panels = [
        {"view_type": v, "s3_key": f"k/{v}", "preview_url": v}
        for v in ("main", "left", "back", "left_front")
    ]
    return SimpleNamespace(data={"data": {"is_turnaround": True, "panels": panels}})


def test_crops_land_in_the_originating_tab_not_the_shown_one(rig):
    events = []
    call = _start(rig, events)

    call["on_success"](_turnaround_response())

    assert rig.added == [rig.agent_tab]
    assert events == [("done", rig.agent_tab, 3)]


def test_single_image_verdict_reaches_the_originating_tab(rig):
    events = []
    call = _start(rig, events)

    call["on_success"](SimpleNamespace(data={"data": {"is_turnaround": False}}))

    assert events == [("single", rig.agent_tab)]


def test_request_error_reaches_the_originating_tab(rig, monkeypatch):
    monkeypatch.setattr(turnaround_detect, "_error_message", lambda e: "boom")
    events = []
    call = _start(rig, events)

    call["on_error"](RuntimeError("502"))

    assert events == [("error", rig.agent_tab, "boom")]


def test_closed_tab_gets_nothing_and_no_other_tab_is_touched(rig):
    events = []
    call = _start(rig, events)
    del rig.open_tabs["session-agent"]

    call["on_success"](_turnaround_response())

    assert rig.added == []
    assert events == []
    assert rig.other_tab.mixie_detect_views_running is False


def _new_chat(rig):
    """New Chat / a loaded chat / a checkpoint reset: same tab, new session."""
    del rig.open_tabs["session-agent"]
    rig.agent_tab.mixie_session_id = "session-new"
    rig.open_tabs["session-new"] = rig.agent_tab


def _assert_released_without_results(rig, events):
    assert rig.added == []
    assert events == []
    assert rig.agent_tab.mixie_detect_views_running is False
    assert rig.agent_tab.mixie_detect_views_status == ""
    assert rig.other_tab.mixie_detect_views_running is False


def test_session_change_before_the_response_releases_the_tab(rig):
    events = []
    call = _start(rig, events)
    _new_chat(rig)

    call["on_success"](_turnaround_response())

    _assert_released_without_results(rig, events)


def test_session_change_before_an_error_releases_the_tab(rig):
    events = []
    call = _start(rig, events)
    _new_chat(rig)

    call["on_error"](RuntimeError("502"))

    _assert_released_without_results(rig, events)


def test_session_change_during_the_crop_download_releases_the_tab(rig, monkeypatch):
    events = []
    call = _start(rig, events)

    def download(url):
        if rig.agent_tab.mixie_session_id != "session-new":
            _new_chat(rig)
        return (f"/tmp/{url}.png", None)

    monkeypatch.setattr(image_utils, "download_image_to_tempfile", download)
    call["on_success"](_turnaround_response())

    _assert_released_without_results(rig, events)


def test_renamed_sessionless_tab_is_released(rig):
    rig.open_tabs.pop("session-agent")
    rig.agent_tab.mixie_session_id = ""
    rig.open_tabs[""] = rig.agent_tab
    events = []
    call = _start(rig, events)
    rig.agent_tab.name = "Renamed"

    call["on_success"](_turnaround_response())

    _assert_released_without_results(rig, events)
