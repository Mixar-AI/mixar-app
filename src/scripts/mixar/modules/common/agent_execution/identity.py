# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Worker identity and per-request ownership checks for the headless pump.

The GUI pump gates on "is there an active agent session"; a background worker
has no chat session, so copying that gate would reject every legitimate
request. Instead the worker validates that a request was ASSIGNED to it:

- an envelope ``execution_target`` (when present) must name this worker;
- the scene routing session must be the worker's own constant
  (``agent:{connection_id}``) or empty — a per-scene session id means the
  backend meant a GUI scene, and running it here would execute against the
  wrong document while reporting success.

The parent/worker relationship itself is authenticated on the backend at
handshake (same user must own both sockets); this module only derives the
ids the worker announces.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

from .request import ExecutionRequest

WORKER_ROLE = "sandbox"
_SUFFIX = "-sbx"


def parent_instance_from(connection_id: str) -> str:
    """Inverse of the backend's ``{parent}-sbx-{n}`` scheme (legacy ``-sbx`` too)."""
    head, sep, tail = connection_id.rpartition(_SUFFIX + "-")
    if sep and tail.isdigit():
        return head
    if connection_id.endswith(_SUFFIX):
        return connection_id[: -len(_SUFFIX)]
    return connection_id


def constant_routing_session(connection_id: str) -> str:
    """The non-scene routing session the backend uses for a worker."""
    return f"agent:{connection_id}"


@dataclass(frozen=True)
class WorkerIdentity:
    connection_id: str
    parent_instance_id: str
    parent_pid: int = 0
    role: str = WORKER_ROLE
    # Parent-created artifact staging directory (MIXAR_SANDBOX_STAGING_DIR).
    # Local to this machine; never reported upstream.
    staging_dir: str = ""

    @property
    def routing_session(self) -> str:
        return constant_routing_session(self.connection_id)


def worker_identity_from_env(env: Optional[Mapping[str, str]] = None) -> WorkerIdentity:
    """Identity from the launch environment written by ``sandbox_supervisor``."""
    env = os.environ if env is None else env
    conn_id = env.get("MIXAR_SANDBOX_CONNECTION_ID", "") or ""
    parent = env.get("MIXAR_SANDBOX_PARENT_INSTANCE_ID", "") or parent_instance_from(conn_id)
    try:
        pid = int(env.get("MIXAR_SANDBOX_PARENT_PID", "0") or 0)
    except ValueError:
        pid = 0
    return WorkerIdentity(
        connection_id=conn_id, parent_instance_id=parent, parent_pid=pid,
        staging_dir=env.get("MIXAR_SANDBOX_STAGING_DIR", "") or "",
    )


def check_assignment(req: ExecutionRequest, identity: WorkerIdentity) -> Optional[str]:
    """Return a rejection reason, or None when this worker may run ``req``."""
    env = req.envelope
    if env is not None and env.execution_target and env.execution_target != identity.connection_id:
        return (
            f"request assigned to {env.execution_target!r}, "
            f"this worker is {identity.connection_id!r}"
        )
    sid = req.session_id or ""
    if sid and sid != identity.routing_session:
        return (
            f"per-scene routing session {sid!r} cannot run on worker "
            f"{identity.connection_id!r}"
        )
    return None
