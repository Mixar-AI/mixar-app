# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure state and work-item types shared across Blender and the Lore worker."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Availability(str, Enum):
    BUILD_DISABLED = "build_disabled"
    SDK_MISSING = "sdk_missing"
    UNSUPPORTED_PLATFORM = "unsupported_platform"
    AVAILABLE = "available"
    LOAD_ERROR = "load_error"


class ProjectState(str, Enum):
    UNLINKED = "unlinked"
    INITIALIZING = "initializing"
    READY = "ready"
    CHECKPOINTING = "checkpointing"
    ERROR = "error"
    SHUTTING_DOWN = "shutting_down"


class CheckpointState(str, Enum):
    QUEUED = "queued"
    STAGING = "staging"
    COMMITTING = "committing"
    SUCCEEDED = "succeeded"
    SUPERSEDED = "superseded"
    FAILED = "failed"


class RemoteOperation(str, Enum):
    CREATE = "create"
    CLONE = "clone"
    PUSH = "push"
    SYNC = "sync"


class RemoteResultState(str, Enum):
    SUCCEEDED = "succeeded"
    UP_TO_DATE = "up_to_date"
    CONFLICT = "conflict"
    FAILED = "failed"


class RemoteConflict(str, Enum):
    DIRTY_WORKTREE = "dirty_worktree"
    LOCAL_AHEAD = "local_ahead"
    DIVERGED = "diverged"
    STALE_REMOTE_HEAD = "stale_remote_head"


@dataclass(frozen=True)
class ProjectRecord:
    project_id: str
    repository_id: str
    identity_id: str
    root_path: str
    blend_path: str
    default_branch: str
    enabled: bool = True
    control_project_id: str | None = None
    remote: bool = False


@dataclass(frozen=True)
class RemoteProjectDescriptor:
    """Non-secret facts shared by every clone of one remote project."""

    project_id: str
    repository_id: str
    control_project_id: str
    default_branch: str = "main"
    primary_blend_path: str = ""


@dataclass(frozen=True)
class RemoteSession:
    """Short-lived Lore authorization material; never persist this object."""

    repository_url: str
    token: str = field(repr=False, compare=False)
    auth_url: str = ""
    token_type: str = "lore"
    identity_id: str = ""
    resource: str = ""
    user_id: str = ""
    control_project_id: str = ""
    branch: str = "main"
    lease_id: str = ""
    lease_token: str = field(default="", repr=False, compare=False)
    lease_expires_at: str = ""
    refresh_after: str = ""
    remote_revision: str | None = None


@dataclass(frozen=True)
class CheckpointRequest:
    request_id: str
    project: ProjectRecord
    filepath: str
    relative_blend_path: str
    source: str
    message: str
    size: int
    mtime_ns: int
    epoch: int
    captured_at: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CheckpointResult:
    request_id: str
    filepath: str
    epoch: int
    state: CheckpointState
    revision: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class RemoteCreateRequest:
    request_id: str
    project: ProjectRecord
    session: RemoteSession
    epoch: int = 0


@dataclass(frozen=True)
class RemoteCloneRequest:
    request_id: str
    repository_path: str
    session: RemoteSession
    revision: str = ""
    epoch: int = 0


@dataclass(frozen=True)
class RemotePushRequest:
    request_id: str
    project: ProjectRecord
    session: RemoteSession
    branch: str = ""
    epoch: int = 0


@dataclass(frozen=True)
class RemoteSyncRequest:
    request_id: str
    project: ProjectRecord
    session: RemoteSession
    branch: str = ""
    epoch: int = 0


RemoteRequest = RemoteCreateRequest | RemoteCloneRequest | RemotePushRequest | RemoteSyncRequest


@dataclass(frozen=True)
class RemoteHeads:
    branch: str
    local_revision: str | None
    remote_revision: str | None
    local_ahead: bool
    remote_ahead: bool
    dirty_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class RemoteTransferOutcome:
    revision: str | None
    changed: bool


@dataclass(frozen=True)
class RemoteOperationResult:
    request_id: str
    operation: RemoteOperation
    state: RemoteResultState
    epoch: int = 0
    revision: str | None = None
    conflict: RemoteConflict | None = None
    error: str | None = None
