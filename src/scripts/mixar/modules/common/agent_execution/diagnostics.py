# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Content-free local execution phases; safe on the socket and main threads.

Wall time comes from the scene dossier. Durations use a monotonic clock, and
no script, output, exception text, image or filesystem path is recorded here.
These are local diagnostics, never remote analytics or result payload fields.
"""

import time

from mixar.modules.common.scenes_log import slog


def record_phase(req, phase: str, result: dict | None = None) -> None:
    """Best-effort receipt through reply trace, correlated by original RPC id."""
    try:
        fields = {
            "request_id": req.request_id,
            "tool": req.tool_name,
            "elapsed_ms": round(max(0.0, time.monotonic() - req.queued_at) * 1000, 1),
        }
        fields.update({key: req.timing[key] for key in
                       ("queue_wait_ms", "exec_ms", "render_wait_ms") if key in req.timing})
        if result is not None:
            fields["success"] = result.get("success") is True
        # chat_session_id is thread-safe and keeps lane diagnostics in the
        # originating chat dossier (lane ids contain Windows-invalid ':').
        session = str((req.agent_ctx or {}).get("chat_session_id") or req.session_id or "")
        slog("execution." + phase, None, session_id=session, **fields)
    except Exception:
        pass  # Diagnostics must never suppress execution or its response.
