# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Getting a recording transcribed: stage the clip, submit, poll, hand back text.

This is a BESPOKE path, deliberately not a `FeatureQueue`. The unified queue's
job is to make long generations visible: it feeds the N-panel Queue list, the
"3 generations in progress" toast and the Agent Bubble's status pill, all of
which read `all_queues()`. A voice note finishes in about a second and is not
a generation the user waits on — putting it on a FeatureQueue would flash a
toast and a queue row for every sentence dictated. The BACKEND still bills and
runs it through its own queue like everything else; only the client-side
visible-work machinery is skipped.

Everything here is callback-driven on Blender's main thread: the shared API
client runs each request on its own thread and delivers the result back on the
main thread, so nothing in this module ever touches `bpy` off-thread.
"""

from __future__ import annotations

import os
import time
from typing import Callable, Optional

import bpy

from mixar.config.logging_config import get_logger

from ..constants import POLL_INTERVAL_S, SERVICE_KEY, TRANSCRIBE_TIMEOUT_S

logger = get_logger(__name__)


def _resolve_model() -> Optional[str]:
    """The catalog's default speech model, or None when it cannot answer.

    None aborts the submit. A literal slug here would be the same mistake
    every other enqueue helper is forbidden from making: the model row set is
    server-owned, so a guess spends the round trip on a 422.
    """
    try:
        from mixar.modules.common.generation_params.core.selector import (
            catalog_default_model,
        )

        return catalog_default_model(SERVICE_KEY)
    except Exception:
        logger.exception("[Voice] could not resolve the speech-to-text model")
        return None


def _response_data(response) -> dict:
    """The inner ``data`` dict of a normalized job-queue response."""
    outer = getattr(response, "data", None)
    if not isinstance(outer, dict):
        return {}
    inner = outer.get("data", outer)
    return inner if isinstance(inner, dict) else {}


class TranscriptionRequest:
    """One recording on its way to text.

    Terminal exactly once: `_finish` is the only place `on_done`/`on_failed`
    fire, and it latches `_settled` first. Without that latch a poll landing in
    the same tick as the timeout would deliver a transcript AND an error for
    the same recording, and the session's state machine would apply both.
    """

    def __init__(
        self,
        filepath: str,
        *,
        on_done: Callable[[str], None],
        on_failed: Callable[[str], None],
    ) -> None:
        self._filepath = filepath
        self._on_done = on_done
        self._on_failed = on_failed
        self._model = ""
        self._job_id = ""
        self._started_at = time.monotonic()
        self._settled = False
        self._cancelled = False

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        model = _resolve_model()
        if not model:
            self._finish(
                False,
                "Voice input isn't ready yet — try again in a moment",
            )
            return
        self._model = model
        self._stage_clip()

    def cancel(self) -> None:
        """Abandon the request. The backend job, if any, is left to finish.

        Cancelling the JOB would be the obvious move and is deliberately not
        done: it is already submitted and charged, it costs one credit, and a
        DELETE racing a completion is a refund path with more ways to go wrong
        than letting a one-second job finish into nobody's hands.
        """
        self._cancelled = True
        self._settled = True
        self._cleanup_file()

    @property
    def settled(self) -> bool:
        return self._settled

    # -- stages ------------------------------------------------------------

    def _stage_clip(self) -> None:
        try:
            size = os.path.getsize(self._filepath)
        except OSError:
            self._finish(False, "The recording could not be read")
            return
        if size <= 0:
            self._finish(False, "The recording was empty")
            return

        from mixar.modules.common.api.services.job_queue_service import (
            get_job_queue_service,
        )

        filepath = self._filepath

        def _body():
            # A factory, not an open handle: the API client re-calls it after
            # an auth refresh, and a retry from an exhausted handle would
            # upload zero bytes.
            return open(filepath, "rb")

        try:
            get_job_queue_service().stage_media(
                media_kind="audio",
                filename=os.path.basename(filepath),
                content_type="audio/wav",
                content_length=size,
                body_factory=_body,
                on_success=self._on_staged,
                on_error=lambda exc: self._on_transport_error("upload", exc),
            )
        except Exception as exc:
            self._on_transport_error("upload", exc)

    def _on_staged(self, response) -> None:
        if self._settled:
            return
        s3_key = str(_response_data(response).get("s3_key") or "")
        if not s3_key:
            self._finish(False, "The recording could not be uploaded")
            return

        from mixar.modules.common.api.services.job_queue_service import (
            get_job_queue_service,
        )

        try:
            get_job_queue_service().enqueue(
                job_type=SERVICE_KEY,
                model=self._model,
                # No params: the catalog defaults (transcribe, auto-detect
                # language) are what dictation wants, and sending "auto"
                # explicitly would be worse than omitting it — see the
                # adapter's language handling.
                payload={"audio_s3_key": s3_key},
                on_success=self._on_submitted,
                on_error=lambda exc: self._on_transport_error("submit", exc),
            )
        except Exception as exc:
            self._on_transport_error("submit", exc)

    def _on_submitted(self, response) -> None:
        if self._settled:
            return
        data = _response_data(response)
        self._job_id = str(data.get("job_id") or "")
        if not self._job_id:
            self._finish(False, "Transcription could not be started")
            return
        # A queue this fast can already be DONE in the submit response.
        if not self._consume_terminal(data):
            self._schedule_poll()

    def _schedule_poll(self) -> None:
        if self._settled:
            return
        bpy.app.timers.register(self._poll, first_interval=POLL_INTERVAL_S)

    def _poll(self) -> Optional[float]:
        if self._settled:
            return None
        if time.monotonic() - self._started_at > TRANSCRIBE_TIMEOUT_S:
            self._finish(False, "Transcription timed out")
            return None

        from mixar.modules.common.api.services.job_queue_service import (
            get_job_queue_service,
        )

        try:
            get_job_queue_service().get_job_status(
                self._job_id,
                on_success=self._on_status,
                # A poll that fails in transit is not a failed transcription:
                # the job is still running on the backend. Keep polling and
                # let the timeout be the thing that gives up.
                on_error=lambda _exc: self._schedule_poll(),
            )
        except Exception:
            self._schedule_poll()
        return None

    def _on_status(self, response) -> None:
        if self._settled:
            return
        if not self._consume_terminal(_response_data(response)):
            self._schedule_poll()

    def _consume_terminal(self, data: dict) -> bool:
        """Settle on a terminal job state. True when the request is finished."""
        status = str(data.get("status") or "").upper()
        if status == "DONE":
            result = data.get("result")
            transcript = ""
            if isinstance(result, dict):
                transcript = str(result.get("transcript") or "")
            # An empty transcript is SILENCE, and silence is a success: the
            # caller says "didn't catch that" rather than raising an error at
            # someone who simply did not speak.
            self._finish(True, transcript)
            return True
        if status in {"FAILED", "DLQ", "CANCELLED"}:
            message = str(data.get("user_message") or "") or "Transcription failed"
            self._finish(False, message)
            return True
        return False

    def _on_transport_error(self, stage: str, exc: Exception) -> None:
        if self._settled:
            return
        logger.warning(f"[Voice] {stage} failed: {exc}")
        try:
            from mixar.modules.common.network import classify_network_error

            # ``user_text`` carries the NET-* support code: a generic
            # "unable to connect" string is banned by the network contract,
            # because the code is what makes a corporate-proxy failure
            # diagnosable without a log file.
            failure = classify_network_error(exc)
            message = failure.user_text
        except Exception:
            message = "Could not reach Mixar — check your connection"
        self._finish(False, message)

    def _finish(self, ok: bool, payload: str) -> None:
        if self._settled:
            return
        self._settled = True
        self._cleanup_file()
        if self._cancelled:
            return
        try:
            if ok:
                self._on_done(payload)
            else:
                self._on_failed(payload)
        except Exception:
            logger.exception("[Voice] transcription callback failed")

    def _cleanup_file(self) -> None:
        """Delete the temp WAV.

        The session temp dir is cleared at exit anyway, but a dictation-heavy
        session would otherwise leave a 10 MB file per sentence sitting there
        for hours.
        """
        try:
            if self._filepath and os.path.exists(self._filepath):
                os.remove(self._filepath)
        except OSError:
            pass
        self._filepath = ""
