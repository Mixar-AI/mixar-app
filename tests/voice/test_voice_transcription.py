# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Staging, submitting and polling one recording.

The contracts pinned here:

- **One settlement.** A poll landing in the same tick as the timeout must not
  deliver a transcript AND an error for the same recording.
- **Silence is a success.** An empty transcript comes back as a DONE result;
  raising there would refund a credit and toast an error at someone who simply
  did not speak.
- **No guessed model slug.** The model row set is server-owned; a literal slug
  spends the round trip on a 422. A catalog that cannot answer aborts.
- **The temp WAV is always cleaned up**, on every terminal path, including a
  failure — a dictation-heavy session would otherwise leave a file per
  sentence behind.
- **Not a FeatureQueue.** Voice is deliberately off the visible queue, or every
  sentence would raise a "1 generation in progress" toast and a queue row.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import pytest  # noqa: E402

from mixar.modules.testing.mock_bpy import install_bpy_mock  # noqa: E402

install_bpy_mock()

from mixar.modules.voice.core import transcription  # noqa: E402


class FakeService:
    def __init__(self, *, stage_key="user-uploads/u1/voice/audios/2500/x/c.wav"):
        self.stage_key = stage_key
        self.staged = []
        self.enqueued = []
        self.polls = 0
        self._stage_cb = None
        self._enqueue_cb = None
        self._poll_cb = None

    def stage_media(self, *, media_kind, filename, content_type, content_length,
                    body_factory, on_success=None, on_error=None, **_kwargs):
        self.staged.append(
            SimpleNamespace(
                media_kind=media_kind,
                filename=filename,
                content_type=content_type,
                content_length=content_length,
                body_factory=body_factory,
            )
        )
        self._stage_cb = on_success

    def enqueue(self, *, job_type, model, payload, on_success=None, **_kwargs):
        self.enqueued.append(
            SimpleNamespace(job_type=job_type, model=model, payload=payload)
        )
        self._enqueue_cb = on_success

    def get_job_status(self, job_id, on_success=None, on_error=None, **_kwargs):
        self.polls += 1
        self._poll_cb = on_success

    # -- test drivers ------------------------------------------------------

    def finish_staging(self):
        self._stage_cb(_response({"s3_key": self.stage_key}))

    def finish_submit(self, **extra):
        self._enqueue_cb(_response({"job_id": "job-1", "status": "PENDING", **extra}))

    def finish_poll(self, request, **data):
        """Drive one poll cycle by hand.

        `_schedule_poll` goes through a Blender timer, which the fixture
        stubs out — so the tick is invoked here instead of waited for.
        """
        request._poll()
        assert self._poll_cb is not None, "the request never polled"
        self._poll_cb(_response(data))


def _response(data: dict):
    return SimpleNamespace(data={"status": "success", "data": data})


@pytest.fixture
def clip(tmp_path):
    path = tmp_path / "voice.wav"
    path.write_bytes(b"RIFF" + b"\x00" * 64)
    return path


@pytest.fixture(autouse=True)
def _no_timers(monkeypatch):
    """Poll scheduling is a Blender timer; drive it by hand instead."""
    monkeypatch.setattr(
        transcription.bpy.app.timers, "register", lambda *a, **k: None, raising=False
    )


@pytest.fixture
def service(monkeypatch):
    fake = FakeService()
    module = SimpleNamespace(get_job_queue_service=lambda: fake)
    monkeypatch.setitem(
        sys.modules, "mixar.modules.common.api.services.job_queue_service", module
    )
    monkeypatch.setattr(transcription, "_resolve_model", lambda: "wizper")
    return fake


def _request(clip, done=None, failed=None):
    return transcription.TranscriptionRequest(
        str(clip),
        on_done=done or (lambda text: None),
        on_failed=failed or (lambda message: None),
    )


# -- the happy path --------------------------------------------------------


def test_the_clip_is_staged_as_audio_and_submitted_by_key(service, clip):
    request = _request(clip)
    request.start()

    assert len(service.staged) == 1
    assert service.staged[0].media_kind == "audio"
    assert service.staged[0].content_type == "audio/wav"
    assert service.staged[0].content_length == clip.stat().st_size

    service.finish_staging()
    assert len(service.enqueued) == 1
    submitted = service.enqueued[0]
    assert submitted.job_type == "speech_to_text"
    assert submitted.payload == {"audio_s3_key": service.stage_key}


def test_the_upload_body_is_a_factory_not_an_open_handle(service, clip):
    """The client re-calls it after an auth refresh.

    Retrying from an exhausted handle would upload zero bytes — and the
    backend would refuse an empty clip, which reads as "the mic did not work".
    """
    request = _request(clip)
    request.start()
    factory = service.staged[0].body_factory
    with factory() as first:
        assert first.read()
    with factory() as second:
        assert second.read(), "the second call handed back an exhausted stream"


def test_a_transcript_reaches_the_caller(service, clip):
    delivered = []
    request = _request(clip, done=delivered.append)
    request.start()
    service.finish_staging()
    service.finish_submit()
    service.finish_poll(request, status="DONE", result={"transcript": "make it taller"})

    assert delivered == ["make it taller"]
    assert request.settled


def test_a_job_already_done_in_the_submit_reply_never_polls(service, clip):
    """Wizper runs at ~250x real time; a voice note can finish immediately."""
    delivered = []
    request = _request(clip, done=delivered.append)
    request.start()
    service.finish_staging()
    service.finish_submit(status="DONE", result={"transcript": "hello"})

    assert delivered == ["hello"]
    assert service.polls == 0


def test_silence_is_delivered_as_an_empty_transcript_not_a_failure(service, clip):
    delivered = []
    failures = []
    request = _request(clip, done=delivered.append, failed=failures.append)
    request.start()
    service.finish_staging()
    service.finish_submit()
    service.finish_poll(request, status="DONE", result={"transcript": ""})

    assert delivered == [""]
    assert failures == []


# -- failure paths ---------------------------------------------------------


def test_a_failed_job_surfaces_the_backend_message(service, clip):
    failures = []
    request = _request(clip, failed=failures.append)
    request.start()
    service.finish_staging()
    service.finish_submit()
    service.finish_poll(request, status="FAILED", user_message="Transcription failed")

    assert failures == ["Transcription failed"]


def test_a_catalog_that_cannot_answer_aborts_instead_of_guessing_a_slug(
    service, clip, monkeypatch
):
    monkeypatch.setattr(transcription, "_resolve_model", lambda: None)
    failures = []
    request = _request(clip, failed=failures.append)
    request.start()

    assert service.staged == []
    assert failures and "ready" in failures[0]


def test_a_missing_file_fails_before_any_upload(service, tmp_path):
    failures = []
    request = _request(tmp_path / "gone.wav", failed=failures.append)
    request.start()

    assert service.staged == []
    assert failures


def test_the_request_settles_exactly_once(service, clip):
    """A late poll must not deliver a second outcome for one recording."""
    delivered = []
    failures = []
    request = _request(clip, done=delivered.append, failed=failures.append)
    request.start()
    service.finish_staging()
    service.finish_submit()
    service.finish_poll(request, status="DONE", result={"transcript": "first"})
    service.finish_poll(request, status="FAILED", user_message="late failure")

    assert delivered == ["first"]
    assert failures == []


def test_the_temp_clip_is_removed_on_every_terminal_path(service, clip):
    request = _request(clip)
    request.start()
    service.finish_staging()
    service.finish_submit()
    service.finish_poll(request, status="FAILED", user_message="nope")

    assert not clip.exists()


def test_cancelling_removes_the_clip_and_stops_polling(service, clip):
    """Cancel abandons the request; the backend job is left to finish.

    Cancelling the JOB would be the obvious move and is deliberately not done:
    it is already submitted and charged, it costs one credit, and a DELETE
    racing a completion is a refund path with more ways to go wrong than
    letting a one-second job finish into nobody's hands.
    """
    delivered = []
    request = _request(clip, done=delivered.append)
    request.start()
    service.finish_staging()
    service.finish_submit()
    polls_before = service.polls

    request.cancel()
    request._poll()  # the tick that was already scheduled still fires

    assert service.polls == polls_before, "a cancelled request kept polling"
    assert delivered == []
    assert not clip.exists()


# -- staying off the visible queue -----------------------------------------


def test_voice_never_goes_through_a_feature_queue():
    """The queue's job is to make long generations VISIBLE.

    `all_queues()` feeds the N-panel queue list, the "N generations in
    progress" toast and the Agent Bubble's status pill. A one-second
    transcription on that machinery would flash all three for every sentence
    dictated. The BACKEND still queues and bills it like any other job.
    """
    import ast

    source = (
        SCRIPTS / "mixar" / "modules" / "voice" / "core" / "transcription.py"
    ).read_text()
    # Names the CODE uses, not the prose: the module's own docstring explains
    # why it is not a FeatureQueue, and a plain substring search reads that
    # explanation as the violation it warns against.
    tree = ast.parse(source)
    used = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    } | {
        alias.name.rsplit(".", 1)[-1]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "enqueue_generation" not in used
    assert "get_queue" not in used
    assert "FeatureQueue" not in used
