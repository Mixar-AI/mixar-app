# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Authenticated relay adapter. No Blender access on the HTTP thread."""

import time
import uuid


def dispatch(request, owner, session):
    from mixar.modules.common.ui_control.constants import UIError
    from mixar.modules.common.ui_control.core import service
    call_id, started = str(uuid.uuid4()), time.monotonic()
    params = {}
    try:
        if request.get("method") != "tools/call" or "id" not in request:
            raise UIError("invalid_request", "Local UI requires an identified tool call")
        params = request.get("params") or {}
        meta = params.get("_meta") or {}
        call_id = str(uuid.UUID(meta.get("mixar/request-id", call_id)))
        result = service.submit(str(uuid.UUID(owner)), params.get("name"),
                                params.get("arguments") or {}, call_id, session)
    except UIError as exc:
        result = service.envelope(exc.result(), call_id, failed=True)
    except (ValueError, TypeError, AttributeError):
        result = service.envelope({"error_type": "invalid_request", "error": "Invalid local UI request"},
                                  call_id, failed=True)
    meta = params.get("_meta") if isinstance(params, dict) else None
    if isinstance(meta, dict) and "mixar/request-id" in meta:
        # Only an AI app's calls; the connector's own release/rebind calls carry no id.
        from .usage import report
        report(params.get("name"), meta, session, result, started)
    return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}
