# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Main-thread pump helpers shared by the GUI executor and the headless worker.

Both pumps do the same four things per request: take the next runnable
request (honouring an asset prefetch hold), execute it under the provenance
context, and reply with the SAME request id. Keeping that sequence here means
the two entrypoints cannot drift again. No ``bpy`` at module level.
"""

from __future__ import annotations

import queue
import time
from typing import Any, Callable, Optional

from mixar.config.logging_config import get_logger

from .request import ExecutionRequest

logger = get_logger(__name__)

# take_next() statuses
EMPTY = "empty"                    # nothing queued
HOLDING = "holding"                # head request's prefetch still pending
READY = "ready"                    # request returned, run it
PREFETCH_FAILED = "prefetch_failed"    # request returned, do NOT run: reply error
PREFETCH_EXPIRED = "prefetch_expired"  # request returned, do NOT run: reply error

# Prefetch handle states (mirrors script_prefetch.ScriptAssetPrefetch.state()).
_PF_PENDING, _PF_READY, _PF_FAILED, _PF_EXPIRED = "pending", "ready", "failed", "expired"


def prefetch_state(prefetch: Any) -> str:
    """State of a prefetch handle; ``ready`` for None or legacy handles."""
    if prefetch is None:
        return _PF_READY
    state_fn = getattr(prefetch, "state", None)
    if callable(state_fn):
        return state_fn()
    # Legacy handle: only ready()/pending known.
    return _PF_READY if prefetch.ready() else _PF_PENDING


def take_next(
    q: "queue.Queue[Any]",
    held: Optional[ExecutionRequest],
    block_s: Optional[float] = None,
) -> tuple[Optional[ExecutionRequest], Optional[ExecutionRequest], str]:
    """Advance the queue by at most one request.

    Returns ``(request, held, status)``: ``request`` is set for READY /
    PREFETCH_* (the caller runs or refuses it); ``held`` is the request kept
    at the head while its assets download (HOLDING). FIFO is preserved —
    nothing behind a held request runs. ``block_s`` makes an empty queue wait
    that long (worker pump); None means non-blocking (timer pump).
    """
    if held is None:
        try:
            item = q.get(timeout=block_s) if block_s else q.get_nowait()
        except queue.Empty:
            return None, None, EMPTY
        held = ExecutionRequest.from_legacy(item)
    state = prefetch_state(held.prefetch)
    if state == _PF_PENDING:
        return None, held, HOLDING
    if state == _PF_FAILED:
        return held, None, PREFETCH_FAILED
    if state == _PF_EXPIRED:
        return held, None, PREFETCH_EXPIRED
    return held, None, READY


def prefetch_refusal(req: ExecutionRequest, status: str) -> dict:
    """Error result for a script whose asset preparation did not complete.

    A failed or expired prefetch must not fall through to an in-script
    download on the main thread (that is the UI freeze the prefetch exists
    to prevent), so the script is refused explicitly and the backend sees
    WHY instead of a stalled or silently degraded execution.
    """
    urls: list[str] = []
    failed = getattr(req.prefetch, "failed_urls", None)
    if callable(failed):
        try:
            urls = list(failed())[:3]
        except Exception:  # noqa: BLE001
            urls = []
    count = getattr(req.prefetch, "url_count", 0)
    if status == PREFETCH_EXPIRED:
        msg = f"asset prefetch timed out ({count} asset(s) still downloading)"
    else:
        msg = f"asset prefetch failed ({len(urls) or 'some'} of {count} asset(s))"
    if urls:
        msg += ": " + "; ".join(urls)
    return {"success": False, "error": msg, "error_type": status}


def resolve_agent_context_ids(
    agent_ctx: Optional[dict], session_id: str, request_id: str
) -> tuple[str, str]:
    """Provenance ids (chat session, turn), retaining compatibility with older backends."""
    if isinstance(agent_ctx, dict):
        return (
            agent_ctx.get("chat_session_id", session_id),
            agent_ctx.get("turn_id", request_id),
        )
    return session_id, request_id


def execute_request(
    req: ExecutionRequest,
    executor: Any,
    on_success: Optional[Callable[[], None]] = None,
) -> dict:
    """Run ``req.script`` through ``executor`` under the provenance context.

    Never raises: any exception becomes a ``{"success": False, "error"}``
    result. ``on_success`` is a best-effort hook (analytics) that cannot
    change the outcome.
    """
    from mixar.modules.common.agent_execution_context import (
        clear_agent_execution_context,
        set_agent_execution_context,
    )

    context_session_id, context_turn_id = resolve_agent_context_ids(
        req.agent_ctx, req.session_id, req.request_id
    )
    started = time.monotonic()
    try:
        set_agent_execution_context(context_session_id, context_turn_id)
        result = executor.execute(req.script)
        result_dict = result.to_dict()
        if result_dict.get("success") and on_success is not None:
            try:
                on_success()
            except Exception:  # noqa: BLE001 — analytics never break execution
                pass
    except Exception as e:  # noqa: BLE001
        logger.error(f"Script execution failed ({req.tool_name}): {e}")
        result_dict = {"success": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        clear_agent_execution_context()
    # Timing stays on the request (logs / metrics), never in the wire result:
    # backend consumers compare result payloads exactly.
    req.timing["exec_ms"] = round((time.monotonic() - started) * 1000, 1)
    req.timing["queue_wait_ms"] = round((started - req.queued_at) * 1000, 1)
    logger.debug(
        "executed %s (id %s) success=%s queue_wait=%sms exec=%sms",
        req.tool_name, req.request_id, result_dict.get("success"),
        req.timing["queue_wait_ms"], req.timing["exec_ms"],
    )
    return result_dict


def respond(client: Any, req: ExecutionRequest, result: dict) -> bool:
    """Reply on the SAME request id. False when nothing was sent."""
    if req.is_notification:
        return False
    if client is None or not getattr(client, "is_connected", False):
        logger.warning(f"No active client, dropping response (id: {req.request_id})")
        return False
    client.queue_response(req.request_id, result)
    return True
