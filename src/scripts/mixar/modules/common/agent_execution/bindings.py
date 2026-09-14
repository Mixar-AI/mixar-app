# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Run activation, turn epochs, task bindings and revocation (client side).

The backend allocates a turn epoch per accepted chat and sends
``agent.execution.activate``. This client keeps the highest accepted epoch
per chat session (memory + journal), refuses anything older, revokes the
prior run on acceptance, and answers every commit's "may this still
publish?" question through :func:`check_commit_allowed`.

Main thread only (the journal is main-thread only).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from mixar.config.logging_config import get_logger

from . import document
from .journal import get_journal

logger = get_logger(__name__)

PROTOCOL_VERSION = "v3"


@dataclass
class RunBinding:
    run_id: str
    session_id: str
    turn_epoch: int
    document_id: Optional[str] = None
    document_epoch: int = 0
    scene_id: Optional[str] = None
    revoked: bool = False
    revoked_tasks: set = field(default_factory=set)
    tasks: dict = field(default_factory=dict)   # (task_id, generation) -> {attempt, fence, worker}


_by_session: dict[str, RunBinding] = {}
_by_run: dict[str, RunBinding] = {}


def reset() -> None:
    """Tests only."""
    _by_session.clear()
    _by_run.clear()


def current(session_id: str) -> Optional[RunBinding]:
    return _by_session.get(session_id)


def for_run(run_id: str) -> Optional[RunBinding]:
    return _by_run.get(run_id)


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def activate(params: dict, journal=None, identity_fn=None) -> dict:
    run_id = params.get("run_id")
    session_id = params.get("session_id")
    epoch = _int(params.get("turn_epoch"), -1)
    if not run_id or not session_id or epoch < 0:
        return {"success": False, "error": "activate requires run_id, session_id, turn_epoch",
                "error_type": "invalid_params"}
    if params.get("protocol_version", PROTOCOL_VERSION) != PROTOCOL_VERSION:
        return {"success": False, "error": "unsupported protocol_version",
                "error_type": "unsupported_protocol"}
    journal = journal or get_journal()
    identity_fn = identity_fn or document.document_identity
    prior = _by_session.get(session_id)
    known = max(prior.turn_epoch if prior else -1, journal.run_epoch(session_id))
    if prior is not None and prior.run_id == run_id and prior.turn_epoch == epoch:
        # Duplicate activate for the same run (transport retry): same answer,
        # unless that run was revoked — an ACK here would tell the backend
        # the client is healthy while every later commit is refused.
        if prior.revoked or journal.run_revoked(run_id):
            return {"success": False,
                    "error": f"run {run_id!r} has been revoked",
                    "error_type": "stale_epoch"}
        identity = identity_fn()
        refused = check_document_current(prior, identity)
        if refused is not None:
            return {"success": False, "error_type": refused[0], "error": refused[1]}
        return _ack(prior, identity)
    if epoch <= known:
        return {"success": False, "error": f"turn_epoch {epoch} is not newer than {known}",
                "error_type": "stale_epoch"}
    # Newer epoch wins: revoke whatever was active for this session.
    if prior is not None:
        _revoke_binding(prior, journal)
    # A new run starts with no foreground task in flight.
    document.clear_foreground_tasks()
    identity = identity_fn()
    binding = RunBinding(
        run_id=run_id, session_id=session_id, turn_epoch=epoch,
        document_id=identity.get("document_id"),
        document_epoch=_int(identity.get("document_epoch")),
        scene_id=identity.get("scene_id"),
    )
    _by_session[session_id] = binding
    _by_run[run_id] = binding
    journal.record_run(session_id, run_id, epoch)
    document.set_run_active(True)
    logger.info("v3 run %s activated (session %s epoch %s)", run_id[:8], session_id[:8], epoch)
    return _ack(binding, identity)


def check_document_current(binding: RunBinding, identity: dict):
    """One document fence for activation retries and foreground commits."""
    live_doc = identity.get("document_id")
    if binding.document_id and live_doc and live_doc != binding.document_id:
        return "stale_document", "document changed since this run activated"
    if _int(identity.get("document_epoch")) != binding.document_epoch:
        return "stale_epoch", "document epoch changed since this run activated"
    return None


def _ack(binding: RunBinding, identity: dict) -> dict:
    return {
        "success": True,
        "ack": True,
        "run_id": binding.run_id,
        "turn_epoch": binding.turn_epoch,
        "document_id": identity.get("document_id"),
        "document_epoch": identity.get("document_epoch"),
        "scene_id": identity.get("scene_id"),
        "scene_name": identity.get("scene_name", ""),
        "capabilities": list(CAPABILITIES),
    }


CAPABILITIES = (
    "exec_envelope_v3", "task_binding_v1", "operation_receipts_v1",
    "native_artifacts_v1", "document_epoch_v1", "runtime_questions_v1",
)


def _revoke_binding(binding: RunBinding, journal) -> None:
    binding.revoked = True
    journal.revoke_run(binding.run_id)
    journal.supersede_run(binding.run_id)
    document.clear_foreground_tasks(binding.run_id)


def revoke(params: dict, journal=None) -> dict:
    """Stop further effects for a run, or mark one task finished.

    With ``task_id``: that task may not commit any more AND, if it was a
    FOREGROUND task, its live-scene lock is released — this is how the backend
    signals a foreground task ended. Without: the whole run is revoked.
    """
    run_id = params.get("run_id")
    binding = _by_run.get(run_id) if run_id else None
    journal = journal or get_journal()
    if binding is None:
        # Unknown here but maybe known to the journal (restart): still refuse
        # later commits and supersede any op the lost run left open.
        if run_id:
            journal.revoke_run(run_id)
            journal.supersede_run(run_id)
            document.clear_foreground_tasks(run_id)
        return {"success": True, "known": False,
                "foreground_tasks": document.foreground_tasks_active()}
    task_id = params.get("task_id")
    if task_id:
        binding.revoked_tasks.add(str(task_id))
        document.set_foreground_task(binding.run_id, str(task_id), False)
    else:
        _revoke_binding(binding, journal)
        if _by_session.get(binding.session_id) is binding:
            document.set_run_active(False)
    return {"success": True, "known": True,
            "foreground_tasks": document.foreground_tasks_active()}


EXECUTION_CLASSES = ("worker", "foreground")


def bind_task(params: dict, journal=None) -> dict:
    run_id = params.get("run_id")
    binding = _by_run.get(run_id) if run_id else None
    if binding is None:
        return {"success": False, "error": "unknown run", "error_type": "unknown_run"}
    if _int(params.get("turn_epoch"), -1) != binding.turn_epoch or binding.revoked:
        return {"success": False, "error": "stale turn_epoch", "error_type": "stale_epoch"}
    task_id = str(params.get("task_id") or "")
    generation = _int(params.get("generation"))
    fence = _int(params.get("fence_token"))
    if not task_id:
        return {"success": False, "error": "task_id required", "error_type": "invalid_params"}
    prev = binding.tasks.get((task_id, generation))
    if prev and prev["fence"] > fence:
        return {"success": False, "error": "older fence than the accepted assignment",
                "error_type": "stale_fence"}
    execution_class = str(params.get("execution_class") or "worker")
    if execution_class not in EXECUTION_CLASSES:
        return {"success": False, "error": f"unknown execution_class {execution_class!r}",
                "error_type": "invalid_params"}
    binding.tasks[(task_id, generation)] = {
        "attempt": _int(params.get("attempt")), "fence": fence,
        "worker": params.get("worker_connection_id") or "",
        "execution_class": execution_class,
    }
    (journal or get_journal()).record_binding(
        run_id, task_id, generation, params.get("worker_connection_id") or "", fence
    )
    # A foreground task drives THIS Blender: stand the lock up until the
    # backend revokes the task. Rebinding (new attempt) keeps it up.
    document.set_foreground_task(run_id, task_id, execution_class == "foreground")
    return {"success": True, "execution_class": execution_class,
            "foreground_tasks": document.foreground_tasks_active()}


def check_commit_allowed(run_id: str, turn_epoch, task_id: str, fence, journal=None):
    """None when a commit may proceed; else ``(error_type, message)``."""
    binding = _by_run.get(run_id)
    journal = journal or get_journal()
    if binding is None:
        return "unknown_run", f"run {run_id!r} is not active on this client"
    if binding.revoked or journal.run_revoked(run_id):
        return "stale_epoch", "run has been revoked"
    if _int(turn_epoch, -1) != binding.turn_epoch:
        return "stale_epoch", f"turn_epoch {turn_epoch} != active {binding.turn_epoch}"
    if task_id in binding.revoked_tasks:
        return "stale_fence", f"task {task_id} was revoked"
    fence = _int(fence)
    bound = None
    for (tid, _gen), info in binding.tasks.items():
        if tid == task_id and (bound is None or info["fence"] > bound["fence"]):
            bound = info
    if bound is None:
        rec = journal.get_latest_binding(run_id, task_id)
        if rec is None:
            return "stale_fence", f"task {task_id} is not bound"
        bound = {"fence": rec["fence"]}
    if fence < bound["fence"]:
        return "stale_fence", f"fence {fence} older than bound {bound['fence']}"
    return None
