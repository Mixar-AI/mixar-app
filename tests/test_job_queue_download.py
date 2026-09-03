# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Result downloads must fail fast, verifiably and retryably.

Production defect these pin: a finished job sat in "Downloading…" for 10+
minutes holding a concurrency slot, with the backend job already DONE and
credits spent. Three causes — no total-transfer deadline (the urlopen
timeout is per-read, so a trickle resets it forever), silent truncation
(``Content-Length`` was never checked, so a short body was imported as a
valid partial GLB) and no retry.

``download_file`` is plain ``urllib`` and is tested directly. The queue
side is exercised through ``FeatureQueue`` where it runs outside Blender,
and pinned at source level with ``ast`` where it cannot be — specifically
the threading contract, which no runtime assertion can express: the
download thread must never touch ``bpy`` or call ``_notify()``.
"""

import ast
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

import bpy

bpy.types.Panel.bl_rna = SimpleNamespace(
    properties={"bl_space_type": SimpleNamespace(enum_items=[])}
)

from mixar.modules.common.job_queue import constants as C
from mixar.modules.common.job_queue.core import downloader as DL
from mixar.modules.common.job_queue.core import queue_download as QD
from mixar.modules.common.job_queue.core import queue_manager as QM
from mixar.modules.common.job_queue.core.job import (
    Job,
    JobState,
    download_substate_text,
)

_CORE = SCRIPTS / "mixar/modules/common/job_queue/core"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeClock:
    """Deterministic stand-in for the downloader's ``time`` module."""

    def __init__(self, start=1000.0):
        self.now = start
        self.slept = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class FakeResponse:
    """Minimal ``urlopen`` result: headers mapping + chunked ``read``."""

    def __init__(self, body, content_length=None, clock=None, per_read_s=0.0,
                 read_error=None, error_after=None):
        self._body = body
        self._pos = 0
        self.headers = (
            {} if content_length is None
            else {"Content-Length": str(content_length)}
        )
        self.closed = False
        self._clock = clock
        self._per_read_s = per_read_s
        self._read_error = read_error
        self._error_after = error_after
        self.reads = 0

    def read(self, size):
        if self._clock is not None and self._per_read_s:
            self._clock.now += self._per_read_s
        if (
            self._read_error is not None
            and self._error_after is not None
            and self.reads >= self._error_after
        ):
            raise self._read_error
        self.reads += 1
        chunk = self._body[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk

    def close(self):
        self.closed = True


@pytest.fixture
def temp_paths(monkeypatch):
    """Record every temp file ``download_file`` creates, and clean up."""
    created = []
    real_mkstemp = DL.tempfile.mkstemp

    def fake_mkstemp(**kwargs):
        fd, path = real_mkstemp(**kwargs)
        created.append(path)
        return fd, path

    monkeypatch.setattr(DL.tempfile, "mkstemp", fake_mkstemp)
    yield created
    for path in created:
        try:
            os.remove(path)
        except OSError:
            pass


def _serve(monkeypatch, *responses):
    """Patch urlopen to yield *responses* (or raise them) in order."""
    calls = []

    def fake_urlopen(url, timeout=None):
        calls.append({"url": url, "timeout": timeout})
        item = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(item, BaseException):
            raise item
        return item

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return calls


# ---------------------------------------------------------------------------
# B — completeness verification
# ---------------------------------------------------------------------------


def test_exact_length_body_succeeds(monkeypatch, temp_paths):
    body = b"x" * 20000
    _serve(monkeypatch, FakeResponse(body, content_length=len(body)))

    path = DL.download_file("https://s3/result.glb")

    assert Path(path).read_bytes() == body
    assert path.endswith(".glb")


def test_truncated_body_raises_and_removes_temp_file(monkeypatch, temp_paths):
    monkeypatch.setattr(DL, "time", FakeClock())
    # Header promises 20000, connection closes after 5000.
    _serve(
        monkeypatch,
        *[FakeResponse(b"y" * 5000, content_length=20000) for _ in range(3)],
    )

    with pytest.raises(DL.DownloadError) as excinfo:
        DL.download_file("https://s3/result.glb")

    message = str(excinfo.value)
    # Both numbers, and the word "incomplete" — not a generic failure.
    assert "incomplete" in message.lower()
    assert "5000" in message and "20000" in message
    assert excinfo.value.user_message == "Download was incomplete — please retry"
    assert temp_paths and not any(os.path.exists(p) for p in temp_paths)


def test_missing_content_length_succeeds_without_verification(
    monkeypatch, temp_paths,
):
    body = b"z" * 12345
    _serve(monkeypatch, FakeResponse(body, content_length=None))

    path = DL.download_file("https://s3/result.glb")

    assert Path(path).read_bytes() == body


def test_unparseable_content_length_is_treated_as_absent(
    monkeypatch, temp_paths,
):
    response = FakeResponse(b"q" * 300)
    response.headers = {"Content-Length": "not-a-number"}
    _serve(monkeypatch, response)

    assert Path(DL.download_file("https://s3/result.glb")).read_bytes() == b"q" * 300


# ---------------------------------------------------------------------------
# A — total transfer deadline
# ---------------------------------------------------------------------------


def test_total_deadline_fires_mid_stream(monkeypatch, temp_paths):
    """A trickling transfer must die on the total deadline, not run forever.

    Each read advances the clock by 1 s and returns bytes, so the per-read
    socket timeout would never fire — this is precisely the production hang.
    """
    clock = FakeClock()
    monkeypatch.setattr(DL, "time", clock)
    body = b"a" * (DL.DOWNLOAD_CHUNK_BYTES * 100)
    _serve(
        monkeypatch,
        FakeResponse(body, content_length=len(body), clock=clock, per_read_s=1.0),
    )

    with pytest.raises(DL.DownloadError) as excinfo:
        DL.download_file("https://s3/result.glb", deadline_s=5.0)

    assert "total time limit" in str(excinfo.value)
    assert excinfo.value.user_message == "Download timed out — please retry"
    # Fired inside the loop rather than after the whole 100-chunk body.
    assert clock.now - 1000.0 < 10.0
    assert temp_paths and not any(os.path.exists(p) for p in temp_paths)


def test_socket_timeout_is_capped_by_remaining_budget(monkeypatch, temp_paths):
    """A wedged read can't overshoot the deadline by a whole socket timeout."""
    clock = FakeClock()
    monkeypatch.setattr(DL, "time", clock)
    body = b"b" * 100
    calls = _serve(monkeypatch, FakeResponse(body, content_length=len(body)))

    DL.download_file("https://s3/result.glb", deadline_s=7.0)

    assert calls[0]["timeout"] == 7.0

    calls2 = _serve(monkeypatch, FakeResponse(body, content_length=len(body)))
    DL.download_file("https://s3/result.glb")
    assert calls2[0]["timeout"] == C.DOWNLOAD_SOCKET_TIMEOUT_S


def test_deadline_is_shorter_than_the_poll_budget():
    """Total worst case (poll + download) must stay inside ~30 minutes."""
    assert C.DOWNLOAD_TOTAL_DEADLINE_S < C.MAX_POLL_DURATION
    # The main-thread watchdog must not beat the worker's own error.
    assert C.DOWNLOAD_WATCHDOG_DEADLINE_S > C.DOWNLOAD_TOTAL_DEADLINE_S


# ---------------------------------------------------------------------------
# C — retry policy
# ---------------------------------------------------------------------------


def test_retries_transient_failures_then_succeeds(monkeypatch, temp_paths):
    clock = FakeClock()
    monkeypatch.setattr(DL, "time", clock)
    body = b"c" * 4096
    attempts = []

    def fake_urlopen(url, timeout=None):
        attempts.append(url)
        if len(attempts) <= 2:
            raise urllib.error.URLError("connection reset")
        return FakeResponse(body, content_length=len(body))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    path = DL.download_file("https://s3/result.glb")

    assert len(attempts) == 3 == C.DOWNLOAD_MAX_ATTEMPTS
    assert Path(path).read_bytes() == body
    # Exponential backoff: 2 s then 4 s, slept in cancel-aware slices.
    expected = (
        C.DOWNLOAD_RETRY_BACKOFF_S
        + C.DOWNLOAD_RETRY_BACKOFF_S * C.DOWNLOAD_RETRY_BACKOFF_FACTOR
    )
    assert clock.slept
    assert abs(sum(clock.slept) - expected) < 0.01
    assert max(clock.slept) <= DL._BACKOFF_SLICE_S


def test_truncation_is_retried(monkeypatch, temp_paths):
    body = b"d" * 8000
    calls = []

    def fake_urlopen(url, timeout=None):
        calls.append(url)
        if len(calls) == 1:
            return FakeResponse(b"d" * 10, content_length=8000)
        return FakeResponse(body, content_length=8000)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(DL, "time", FakeClock())

    assert Path(DL.download_file("https://s3/x.glb")).read_bytes() == body
    assert len(calls) == 2


def test_4xx_is_not_retried(monkeypatch, temp_paths):
    calls = []

    def fake_urlopen(url, timeout=None):
        calls.append(url)
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(DL.DownloadError) as excinfo:
        DL.download_file("https://s3/expired.glb")

    # A presigned S3 URL that 403s will keep 403ing — one attempt only, and
    # the user is told to rerun the job rather than left spinning.
    assert len(calls) == 1
    assert "expired" in excinfo.value.user_message.lower()
    assert excinfo.value.retryable is False
    assert temp_paths and not any(os.path.exists(p) for p in temp_paths)


def test_404_is_not_retried(monkeypatch, temp_paths):
    calls = []

    def fake_urlopen(url, timeout=None):
        calls.append(url)
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(DL.DownloadError):
        DL.download_file("https://s3/gone.glb")
    assert len(calls) == 1


def test_5xx_is_retried(monkeypatch, temp_paths):
    calls = []

    def fake_urlopen(url, timeout=None):
        calls.append(url)
        raise urllib.error.HTTPError(url, 503, "Unavailable", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(DL, "time", FakeClock())

    with pytest.raises(DL.DownloadError):
        DL.download_file("https://s3/busy.glb")
    assert len(calls) == C.DOWNLOAD_MAX_ATTEMPTS


def test_retry_never_outlives_the_deadline(monkeypatch, temp_paths):
    """Retries share the deadline; they must not extend it past URL expiry."""
    clock = FakeClock()
    monkeypatch.setattr(DL, "time", clock)
    calls = []

    def fake_urlopen(url, timeout=None):
        calls.append(url)
        raise urllib.error.URLError("reset")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(DL.DownloadError):
        # Budget is smaller than the first 2 s backoff, so no retry fits.
        DL.download_file("https://s3/x.glb", deadline_s=1.0)

    assert len(calls) == 1
    assert clock.slept == []


# ---------------------------------------------------------------------------
# E — cancellation
# ---------------------------------------------------------------------------


def test_cancel_aborts_mid_stream_and_removes_temp_file(
    monkeypatch, temp_paths,
):
    body = b"e" * (DL.DOWNLOAD_CHUNK_BYTES * 50)
    response = FakeResponse(body, content_length=len(body))
    _serve(monkeypatch, response)

    def should_cancel():
        return response.reads >= 3

    with pytest.raises(DL.DownloadCancelled):
        DL.download_file("https://s3/x.glb", should_cancel=should_cancel)

    # Aborted between chunks rather than downloading all 50 and discarding.
    assert response.reads < 10
    assert response.closed
    assert temp_paths and not any(os.path.exists(p) for p in temp_paths)


def test_cancel_during_backoff_aborts(monkeypatch, temp_paths):
    clock = FakeClock()
    monkeypatch.setattr(DL, "time", clock)
    calls = []

    def fake_urlopen(url, timeout=None):
        calls.append(url)
        raise urllib.error.URLError("reset")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(DL.DownloadCancelled):
        DL.download_file("https://s3/x.glb", should_cancel=lambda: True)

    assert len(calls) == 1
    assert temp_paths and not any(os.path.exists(p) for p in temp_paths)


# ---------------------------------------------------------------------------
# D — progress reporting
# ---------------------------------------------------------------------------


def test_progress_is_reported_with_total(monkeypatch, temp_paths):
    clock = FakeClock()
    monkeypatch.setattr(DL, "time", clock)
    body = b"f" * (DL.DOWNLOAD_CHUNK_BYTES * 4)
    response = FakeResponse(
        body, content_length=len(body), clock=clock,
        per_read_s=C.DOWNLOAD_PROGRESS_INTERVAL_S,
    )
    _serve(monkeypatch, response)
    seen = []

    DL.download_file(
        "https://s3/x.glb", on_progress=lambda *a: seen.append(a),
    )

    assert seen[0] == (0, len(body), 1)
    assert seen[-1] == (len(body), len(body), 1)
    assert [s[0] for s in seen] == sorted(s[0] for s in seen)


def test_progress_is_throttled(monkeypatch, temp_paths):
    """No update per 8 KB chunk — the clock never advances here, so the
    only reports are the initial and final ones."""
    monkeypatch.setattr(DL, "time", FakeClock())
    body = b"g" * (DL.DOWNLOAD_CHUNK_BYTES * 40)
    _serve(monkeypatch, FakeResponse(body, content_length=len(body)))
    seen = []

    DL.download_file("https://s3/x.glb", on_progress=lambda *a: seen.append(a))

    assert len(seen) == 2


def test_progress_reports_zero_total_when_length_unknown(
    monkeypatch, temp_paths,
):
    monkeypatch.setattr(DL, "time", FakeClock())
    body = b"h" * 500
    _serve(monkeypatch, FakeResponse(body, content_length=None))
    seen = []

    DL.download_file("https://s3/x.glb", on_progress=lambda *a: seen.append(a))

    assert seen[0] == (0, 0, 1)
    # Final report substitutes the transferred count so the row never shows
    # "12.4 / 0.0 MB".
    assert seen[-1] == (500, 500, 1)


@pytest.mark.parametrize(
    "transferred,total,attempt,expected",
    [
        (0, 0, 1, "Downloading…"),
        (0, 50331648, 1, "Downloading…"),
        (13002342, 50331648, 1, "Downloading… 12.4 / 48.0 MB"),
        (13002342, 0, 1, "Downloading… 12.4 MB"),
        (13002342, 50331648, 2, "Retrying download… (attempt 2) 12.4 / 48.0 MB"),
    ],
)
def test_download_substate_text(transferred, total, attempt, expected):
    assert download_substate_text(transferred, total, attempt) == expected


def test_job_substate_text_uses_progress():
    job = Job()
    job.state = JobState.RUNNING_DOWNLOAD
    assert job.substate_text() == "Downloading…"
    job.download_bytes = 13002342
    job.download_total_bytes = 50331648
    job.download_attempt = 1
    assert job.substate_text() == "Downloading… 12.4 / 48.0 MB"


# ---------------------------------------------------------------------------
# Queue side — watchdog, terminal guards, progress refresh
# ---------------------------------------------------------------------------


class _StubJob(Job):
    def submit(self, on_success, on_error):  # pragma: no cover - unused
        raise NotImplementedError

    def parse_submit_response(self, response):  # pragma: no cover - unused
        raise NotImplementedError

    def parse_poll_response(self, response):  # pragma: no cover - unused
        raise NotImplementedError


@pytest.fixture
def queue(monkeypatch):
    """A FeatureQueue with bpy timers and viewport redraws neutralised."""
    QM._queues.clear()
    QM._sync_watchdog_registered = False
    monkeypatch.setattr(QM, "redraw_3d_views", lambda: None)
    monkeypatch.setattr(QD, "redraw_3d_views", lambda: None, raising=False)
    monkeypatch.setattr(
        QM.bpy.app.timers, "register", lambda *a, **k: None,
    )
    q = QM.FeatureQueue("test_download")
    yield q
    QM._queues.clear()
    QM._sync_watchdog_registered = False


def _downloading_job(queue, age_s):
    job = _StubJob(label="job", feature_key="test_download")
    job.state = JobState.RUNNING_DOWNLOAD
    job.backend_job_id = "backend-1"
    # The watchdog ignores a non-positive download_started_at, so the start
    # stamp has to stay above zero. time.monotonic() counts from boot and is
    # only a few hundred seconds on a freshly started machine, which made
    # "now - deadline" go negative and silently skipped the deadline check.
    job.download_started_at = max(QM.time.monotonic() - age_s, 1e-6)
    queue._jobs.append(job)
    return job


def _watchdog_tick(monkeypatch):
    """Register the sync watchdog and hand back its timer callback."""
    captured = []
    monkeypatch.setattr(
        QM.bpy.app.timers, "register",
        lambda fn, **k: captured.append(fn),
    )
    monkeypatch.setattr(QM, "_request_backend_job_sync", lambda: True)
    QM._sync_watchdog_registered = False
    QM._ensure_sync_watchdog()
    assert captured
    return captured[0]


def test_watchdog_fails_a_stranded_download(queue, monkeypatch):
    """The defect: _fail_timed_out hard-returned on any non-RUNNING_POLL
    state, so a download whose worker thread died was never bounded."""
    QM._queues["test_download"] = queue
    cancelled = []
    monkeypatch.setattr(
        QM.FeatureQueue, "_cancel_on_backend",
        staticmethod(lambda job_id: cancelled.append(job_id)),
    )
    job = _downloading_job(queue, C.DOWNLOAD_WATCHDOG_DEADLINE_S + 60)

    _watchdog_tick(monkeypatch)()

    assert job.state == JobState.FAILED
    assert job.user_message == "Download timed out — please retry"
    # The generation already succeeded and was paid for — only the transfer
    # was lost, so the backend job must NOT be cancelled.
    assert cancelled == []


def test_watchdog_leaves_a_healthy_download_alone(queue, monkeypatch):
    """RUNNING_DOWNLOAD used to fall outside every watchdog state set, so the
    watchdog unregistered itself the instant a job started downloading."""
    QM._queues["test_download"] = queue
    job = _downloading_job(queue, 5.0)

    result = _watchdog_tick(monkeypatch)()

    assert job.state == JobState.RUNNING_DOWNLOAD
    # Non-None keeps the timer alive: RUNNING_DOWNLOAD must not retire it.
    assert result == QM._SYNC_WATCHDOG_INTERVAL


def test_watchdog_retires_when_only_terminal_jobs_remain(queue, monkeypatch):
    QM._queues["test_download"] = queue
    job = _downloading_job(queue, 5.0)
    job.state = JobState.SUCCESS

    assert _watchdog_tick(monkeypatch)() is None


def test_running_download_is_a_watchdog_but_not_a_sync_state():
    # Nothing to reconcile with the backend during a download (the job is
    # already DONE there) — but the tick must keep running to bound it.
    assert JobState.RUNNING_DOWNLOAD in QM._WATCHDOG_STATES
    assert JobState.RUNNING_DOWNLOAD not in QM._BACKEND_SYNC_STATES


def test_finish_import_does_not_resurrect_a_failed_job(queue, monkeypatch):
    imported = []
    monkeypatch.setattr(
        QD, "import_file", lambda *a, **k: imported.append(a) or "Cube",
    )
    job = _downloading_job(queue, 1.0)
    job.state = JobState.FAILED  # watchdog got there first

    fd, path = DL.tempfile.mkstemp(suffix=".glb", prefix="mixar_result_")
    os.close(fd)
    queue._finish_import(job, path, "GLB")

    assert job.state == JobState.FAILED
    assert imported == []
    assert not os.path.exists(path)


def test_finish_failed_keeps_the_first_terminal_verdict(queue):
    job = _downloading_job(queue, 1.0)
    job.state = JobState.FAILED
    job.user_message = "Download timed out — please retry"

    queue._finish_failed(job, "Download failed: something else", "Other")

    assert job.user_message == "Download timed out — please retry"


def test_begin_download_wires_progress_and_cancel(queue, monkeypatch):
    captured = {}

    def fake_download_file(url, file_type, **kwargs):
        captured.update(kwargs)
        captured["url"] = url
        raise RuntimeError("stop before the thread does anything real")

    monkeypatch.setattr(QD, "download_file", fake_download_file)
    monkeypatch.setattr(QD.threading, "Thread", _InlineThread)
    job = _StubJob(label="job", feature_key="test_download")
    job.state = JobState.RUNNING_DOWNLOAD
    queue._jobs.append(job)

    queue._begin_download(
        job, [{"type": "GLB", "url": "https://s3/result.glb"}],
    )

    assert captured["url"] == "https://s3/result.glb"
    on_progress = captured["on_progress"]
    should_cancel = captured["should_cancel"]

    assert should_cancel() is False
    job.state = JobState.CANCELLED
    assert should_cancel() is True

    # on_progress must only write plain values onto the job.
    on_progress(4096, 8192, 2)
    assert (job.download_bytes, job.download_total_bytes, job.download_attempt) \
        == (4096, 8192, 2)
    assert job.download_started_at > 0


class _InlineThread:
    """Run the download body synchronously so the test stays deterministic."""

    def __init__(self, target=None, daemon=False, **kwargs):
        self._target = target

    def start(self):
        self._target()


def test_progress_timer_notifies_only_on_change(queue, monkeypatch):
    """The queue UIList reads substate_text off the WindowManager mirror, and
    only _notify() rebuilds that mirror — so a main-thread tick is what makes
    thread-written byte counts visible."""
    registered = []
    monkeypatch.setattr(
        QM.bpy.app.timers, "register",
        lambda fn, **k: registered.append((fn, k)),
    )
    notifies = []
    monkeypatch.setattr(
        QM.FeatureQueue, "_notify", lambda self: notifies.append(1),
    )
    job = _downloading_job(queue, 1.0)

    queue._start_download_progress_timer(job)
    assert registered
    tick, kwargs = registered[0]
    assert kwargs["first_interval"] == C.DOWNLOAD_PROGRESS_REFRESH_S

    # First tick: 0 bytes differs from the -1 sentinel.
    assert tick() == C.DOWNLOAD_PROGRESS_REFRESH_S
    assert len(notifies) == 1
    # Stalled — no redundant mirror rebuilds.
    assert tick() == C.DOWNLOAD_PROGRESS_REFRESH_S
    assert len(notifies) == 1
    job.download_bytes = 8192
    assert tick() == C.DOWNLOAD_PROGRESS_REFRESH_S
    assert len(notifies) == 2
    # Leaving RUNNING_DOWNLOAD unregisters the timer.
    job.state = JobState.SUCCESS
    assert tick() is None


# ---------------------------------------------------------------------------
# Threading contract — source-level, because no runtime assertion can express
# "this closure runs off the main thread". Same ast pinning pattern as
# tests/moodboard/test_turnaround_operator_wiring.py.
# ---------------------------------------------------------------------------


def _nested_func(path, outer, inner):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == outer:
            for child in ast.walk(node):
                if isinstance(child, ast.FunctionDef) and child.name == inner:
                    return child
    raise AssertionError(f"{path}: {outer}.{inner} not found")


def _attr_chains(node):
    """Dotted names referenced anywhere inside *node*, e.g. bpy.app.timers."""
    chains = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute):
            parts = []
            cur = child
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
                chains.add(".".join(reversed(parts)))
    return chains


def test_on_progress_touches_neither_bpy_nor_notify():
    node = _nested_func(
        _CORE / "queue_download.py", "_begin_download", "_on_progress",
    )
    chains = _attr_chains(node)
    assert not [c for c in chains if c.startswith("bpy")], chains
    assert not [c for c in chains if c.endswith("_notify")], chains


def test_bg_download_reaches_the_main_thread_only_via_timers():
    node = _nested_func(
        _CORE / "queue_download.py", "_begin_download", "_bg_download",
    )
    chains = _attr_chains(node)
    bpy_uses = {c for c in chains if c.startswith("bpy")}
    # bpy.app.timers.register is the ONLY sanctioned hop back to the main
    # thread from the download thread.
    assert bpy_uses <= {"bpy.app", "bpy.app.timers", "bpy.app.timers.register"}, \
        bpy_uses
    assert not [c for c in chains if c.endswith("_notify")], chains


def test_progress_timer_is_the_main_thread_refresh_path():
    tree = ast.parse((_CORE / "queue_download.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) \
                and node.name == "_start_download_progress_timer":
            chains = _attr_chains(node)
            assert "bpy.app.timers.register" in chains
            assert "self._notify" in chains
            return
    raise AssertionError("_start_download_progress_timer not found")
