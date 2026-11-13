# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generation features refused while a restricted connection's script runs.

The Claude plugin's MCP connection may not generate AI images, video or audio
(Anthropic's directory policy). For its calls the backend names the job-queue
features to refuse in ``mcp.begin_operation`` (``blocked_job_features``,
kept on the lease), and the executor holds them in force with ``blocking``
while a script that operation authorized runs. Meanwhile:

- ``FeatureQueue.submit`` refuses a job of a blocked feature (``refuse``):
  every operator, ``enqueue_generation`` and agent batch submits through it;
- a submit made around the queue (``JobQueueService.enqueue`` called directly,
  not by the queue's own pump) is refused outright (``check_direct_submit``).

Nothing else opens a window, so for the in-app agent, other AI apps and the
user's own clicks each check is one empty-list test. A window belongs to the
thread that opened it (the main thread, which runs scripts) and only ever adds
features; scripts cannot import this module (``sandbox_modules``), so a script
cannot lift its own block. Work a script defers past its end (a timer it
registers) runs outside the window; the backend stays the authority.
"""

from contextlib import contextmanager
from contextvars import ContextVar
import threading

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

#: What the agent channel and the script's output say about a refused job.
REASON = "{feature} generation is not available in this connection; nothing was queued or charged."
DIRECT = ("Generation is not available in this connection outside Mixar's job queue; "
          "nothing was queued or charged.")

_EMPTY = frozenset()
_windows = []  # (thread ident, features); main thread only, innermost last
_refusal = {"message": ""}  # The open window's latest refusal (agent reason channel).
_admitted = ContextVar("mixar_job_queue_admitted", default=False)


def blocked() -> frozenset:
    """The features refused on this thread now (empty outside a window)."""
    if not _windows:
        return _EMPTY
    me = threading.get_ident()
    return _EMPTY.union(*(features for thread, features in tuple(_windows) if thread == me))


@contextmanager
def blocking(features):
    """Refuse ``features`` on this thread until the block ends (adds to any outer one)."""
    features = frozenset(features or ())
    if not features:
        yield
        return
    entry = (threading.get_ident(), features)
    _windows.append(entry)
    try:
        yield
    finally:
        for index in range(len(_windows) - 1, -1, -1):
            if _windows[index] is entry:
                del _windows[index]
                break
        if not blocked():
            _refusal["message"] = ""


def refuse(feature_key, context) -> bool:
    """True when ``feature_key`` is blocked now: the reason is recorded for the
    agent (``mixar_agent_gen_reason``), printed into the script's output and
    logged, and the caller queues nothing."""
    if feature_key not in blocked():
        return False
    message = REASON.format(feature=feature_key)
    logger.warning("[JobQueue] refused %s job in a connection without media generation", feature_key)
    from mixar.modules.common.utils.agent_feedback import set_agent_gen_reason
    _refusal["message"] = ""
    set_agent_gen_reason(context, message)
    _refusal["message"] = message
    print(message)  # The executor captures stdout: the model reads why.
    return True


def refusal() -> str:
    """The open window's latest refusal, which an operator's own follow-up
    failure text (``set_agent_gen_reason``) must not replace."""
    return _refusal["message"] if blocked() else ""


def forget_refusal() -> None:
    """A new generation invocation starts (``clear_agent_gen_reason``)."""
    _refusal["message"] = ""


@contextmanager
def admitted():
    """The queue's own pump submitting a job ``FeatureQueue.submit`` accepted."""
    token = _admitted.set(True)
    try:
        yield
    finally:
        _admitted.reset(token)


def check_direct_submit() -> None:
    """Raise PermissionError for a job submit made around the queue in a window."""
    if blocked() and not _admitted.get():
        logger.warning("[JobQueue] refused a direct job submit in a connection without media generation")
        raise PermissionError(DIRECT)
