# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The execution request value type shared by every script pump.

``ExecutionRequest`` replaces the positional queue tuple. ``ExecutionEnvelope``
is the OPTIONAL v3 task envelope the backend may attach to a
``blender.execute_script`` frame (``params["envelope"]``); it is parsed with
bounds and carried through, but PR 1 does not admit tasks on it — only the
headless worker uses ``execution_target`` to refuse work assigned elsewhere.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

NOTIFICATION_ID = "notification"

# Bounded string fields; anything longer is dropped, never truncated silently
# into a different identity.
_MAX_ID_LEN = 200
_STR_FIELDS = (
    "protocol_version", "run_id", "session_id", "task_id", "attempt",
    "fence_token", "operation_id", "payload_hash", "execution_target",
    "document_id", "scene_id", "snapshot_id",
)
_INT_FIELDS = ("turn_epoch", "task_generation", "document_epoch")


@dataclass(frozen=True)
class ExecutionEnvelope:
    """Validated subset of the backend's v3 task envelope (all optional)."""

    protocol_version: Optional[str] = None
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    turn_epoch: Optional[int] = None
    task_id: Optional[str] = None
    task_generation: Optional[int] = None
    attempt: Optional[str] = None
    fence_token: Optional[str] = None
    operation_id: Optional[str] = None
    payload_hash: Optional[str] = None
    execution_target: Optional[str] = None
    document_id: Optional[str] = None
    document_epoch: Optional[int] = None
    scene_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    deadline: Optional[float] = None
    dropped: tuple[str, ...] = ()

    @classmethod
    def parse(cls, raw: Any) -> Optional["ExecutionEnvelope"]:
        """Parse a raw dict; None for absent/non-dict input.

        Out-of-bounds or wrongly typed fields are recorded in ``dropped``
        (and left None) so a caller that needs them can refuse explicitly.
        """
        if not isinstance(raw, dict):
            return None
        values: dict[str, Any] = {}
        dropped: list[str] = []
        for key in _STR_FIELDS:
            val = raw.get(key)
            if val is None:
                continue
            if isinstance(val, str) and 0 < len(val) <= _MAX_ID_LEN:
                values[key] = val
            else:
                dropped.append(key)
        for key in _INT_FIELDS:
            val = raw.get(key)
            if val is None:
                continue
            if isinstance(val, int) and not isinstance(val, bool) and val >= 0:
                values[key] = val
            else:
                dropped.append(key)
        deadline = raw.get("deadline")
        if deadline is not None:
            if isinstance(deadline, (int, float)) and not isinstance(deadline, bool):
                values["deadline"] = float(deadline)
            else:
                dropped.append("deadline")
        return cls(dropped=tuple(dropped), **values)


@dataclass
class ExecutionRequest:
    """One queued ``blender.execute_script`` request."""

    request_id: str
    script: str
    tool_name: str = "unknown"
    session_id: str = ""            # scene ROUTING session (not the chat session)
    agent_ctx: Optional[dict] = None
    prefetch: Any = None            # ScriptAssetPrefetch handle or None
    envelope: Optional[ExecutionEnvelope] = None
    queued_at: float = field(default_factory=time.monotonic)
    timing: dict = field(default_factory=dict)   # filled by pump.execute_request

    @property
    def is_notification(self) -> bool:
        return not self.request_id or self.request_id == NOTIFICATION_ID

    @classmethod
    def from_rpc_params(
        cls,
        params: dict,
        request_id: Optional[str],
        prefetch: Any = None,
    ) -> "ExecutionRequest":
        """Build from a decoded JSON-RPC ``params`` dict."""
        return cls(
            request_id=request_id or NOTIFICATION_ID,
            script=params.get("script", "") or "",
            tool_name=params.get("tool_name", "unknown") or "unknown",
            session_id=params.get("session_id", "") or "",
            agent_ctx=params.get("agent_ctx") if isinstance(params.get("agent_ctx"), dict) else None,
            prefetch=prefetch,
            envelope=ExecutionEnvelope.parse(params.get("envelope")),
        )

    @classmethod
    def from_legacy(cls, item: Any) -> "ExecutionRequest":
        """Adapt a legacy queue tuple (4 or 6 fields) — compatibility only."""
        if isinstance(item, ExecutionRequest):
            return item
        fields = list(item)
        while len(fields) < 6:
            fields.append(None)
        request_id, script, tool_name, session_id, agent_ctx, prefetch = fields[:6]
        return cls(
            request_id=request_id or NOTIFICATION_ID,
            script=script or "",
            tool_name=tool_name or "unknown",
            session_id=session_id or "",
            agent_ctx=agent_ctx if isinstance(agent_ctx, dict) else None,
            prefetch=prefetch,
        )

    def as_tuple(self) -> tuple:
        """The six-field legacy shape, for consumers not yet migrated."""
        return (
            self.request_id, self.script, self.tool_name, self.session_id,
            self.agent_ctx, self.prefetch,
        )
