# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Narrow v0.8.5 Lore SDK adapter, imported only by the checkpoint worker."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .models import (
    ProjectRecord,
    RemoteConflict,
    RemoteHeads,
    RemoteSession,
    RemoteTransferOutcome,
)


class LoreAdapterError(RuntimeError):
    pass


class LoreRemoteConflict(LoreAdapterError):
    def __init__(self, reason: RemoteConflict, heads: RemoteHeads):
        super().__init__(reason.value)
        self.reason = reason
        self.heads = heads


def _validated_endpoint(value: str, *, schemes: set[str], label: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in schemes
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise LoreAdapterError(f"Invalid {label} returned by the control plane")
    return value


def _hex(value: bytes) -> str | None:
    return value.hex() if value and any(value) else None


class LoreSdkAdapter:
    def __init__(self) -> None:
        self._loaded = False
        self._lore: Any = None
        self._types: dict[str, Any] = {}

    def _load(self) -> None:
        if self._loaded:
            return
        try:
            from lore import Lore
            from lore.types.args import (
                LoreAuthLoginWithTokenArgs,
                LoreAuthLogoutArgs,
                LoreBranchPushArgs,
                LoreFileStageArgs,
                LoreGlobalArgs,
                LoreRepositoryCloneArgs,
                LoreRepositoryCreateArgs,
                LoreRepositoryStatusArgs,
                LoreRevisionCommitArgs,
                LoreRevisionSyncArgs,
            )
            from lore.types.events import (
                LoreBranchPushEventData,
                LoreRepositoryStatusFileEventData,
                LoreRepositoryStatusRevisionEventData,
                LoreRevisionCommitRevisionEventData,
                LoreRevisionSyncRevisionEventData,
            )
        except Exception as exc:  # native load failures are capability failures
            raise LoreAdapterError(f"Lore SDK unavailable: {exc}") from exc
        self._lore = Lore
        self._types = {
            "global": LoreGlobalArgs,
            "auth_login": LoreAuthLoginWithTokenArgs,
            "auth_logout": LoreAuthLogoutArgs,
            "branch_push": LoreBranchPushArgs,
            "clone": LoreRepositoryCloneArgs,
            "create": LoreRepositoryCreateArgs,
            "status": LoreRepositoryStatusArgs,
            "stage": LoreFileStageArgs,
            "commit": LoreRevisionCommitArgs,
            "sync": LoreRevisionSyncArgs,
            "push_event": LoreBranchPushEventData,
            "status_file_event": LoreRepositoryStatusFileEventData,
            "status_revision_event": LoreRepositoryStatusRevisionEventData,
            "revision_event": LoreRevisionCommitRevisionEventData,
            "sync_event": LoreRevisionSyncRevisionEventData,
        }
        self._loaded = True

    def _globals(self, project: ProjectRecord, *, offline: bool = True):
        self._load()
        return self._types["global"](
            repository_path=project.root_path,
            identity=project.identity_id,
            offline=offline,
        )

    def _remote_globals(self, repository_path: str, session: RemoteSession):
        self._load()
        return self._types["global"](
            repository_path=repository_path,
            identity=session.identity_id,
            offline=False,
        )

    def authenticate(self, repository_path: str, session: RemoteSession) -> None:
        self._load()
        remote = _validated_endpoint(
            session.repository_url, schemes={"lore"}, label="Lore repository URL"
        )
        auth = (
            _validated_endpoint(
                session.auth_url, schemes={"ucs-auth", "https"}, label="Lore auth URL"
            )
            if session.auth_url
            else ""
        )
        if not session.token:
            raise LoreAdapterError("Lore session token is empty")
        self._lore.auth_login_with_token(
            self._remote_globals(repository_path, session),
            self._types["auth_login"](
                remote_url=remote,
                token=session.token,
                token_type=session.token_type,
                auth_url=auth,
            ),
        ).collect()

    def logout(self, repository_path: str, session: RemoteSession) -> None:
        """Remove only this scoped identity when the broker supplied its keys."""
        if not (self._loaded and session.resource and session.user_id):
            return
        try:
            self._lore.auth_logout(
                self._remote_globals(repository_path, session),
                self._types["auth_logout"](
                    auth_url=session.auth_url,
                    resource=session.resource,
                    user_id=session.user_id,
                ),
            ).collect()
        except Exception:
            pass

    def ensure_repository(self, project: ProjectRecord) -> None:
        self._load()
        # ProjectStore guarantees a foreign `.lore` is never adopted. Existing
        # Mixar repositories are idempotently reused without a create call.
        from pathlib import Path

        # A directory alone may be residue from a failed create. Only a real
        # repository config is authoritative; otherwise retry create with the
        # same stable IDs so timeout recovery is deterministic.
        if (Path(project.root_path) / ".lore" / "config.toml").is_file():
            return
        self._lore.repository_create(
            self._globals(project),
            self._types["create"](
                repository_url=f"mixar-{project.project_id}",
                id=project.repository_id,
            ),
        ).wait()

    def create_remote_repository(
        self, project: ProjectRecord, session: RemoteSession
    ) -> None:
        self.authenticate(project.root_path, session)
        config = Path(project.root_path) / ".lore" / "config.toml"
        if config.is_file():
            return
        self._lore.repository_create(
            self._remote_globals(project.root_path, session),
            self._types["create"](
                repository_url=session.repository_url,
                id=project.repository_id,
            ),
        ).wait()

    def clone_remote(
        self, repository_path: str, session: RemoteSession, *, revision: str = ""
    ) -> None:
        destination = Path(repository_path).expanduser().resolve()
        if destination.exists() and any(destination.iterdir()):
            raise LoreAdapterError("Clone destination must be empty")
        destination.mkdir(parents=True, exist_ok=True)
        self.authenticate(str(destination), session)
        self._lore.repository_clone(
            self._remote_globals(str(destination), session),
            self._types["clone"](
                repository_url=session.repository_url,
                revision=revision,
                direct_file_io=True,
            ),
        ).wait()

    def stage(self, project: ProjectRecord, paths: list[str]) -> None:
        self._load()
        self._lore.file_stage(
            self._globals(project),
            self._types["stage"](paths=paths, scan=True),
        ).wait()

    def commit(self, project: ProjectRecord, message: str) -> str:
        self._load()
        events = self._lore.revision_commit(
            self._globals(project),
            self._types["commit"](message=message, stats=True),
        ).collect()
        for event in events:
            if isinstance(event, self._types["revision_event"]):
                return event.revision.hex()
        raise LoreAdapterError("Lore commit completed without a revision event")

    def remote_heads(
        self, project: ProjectRecord, session: RemoteSession, *, branch: str = ""
    ) -> RemoteHeads:
        self.authenticate(project.root_path, session)
        events = self._lore.repository_status(
            self._remote_globals(project.root_path, session),
            self._types["status"](staged=True, scan=True, sync_point=True),
        ).collect()
        revision_event = None
        dirty_paths = []
        for event in events:
            if isinstance(event, self._types["status_revision_event"]):
                revision_event = event
            elif isinstance(event, self._types["status_file_event"]):
                if event.flag_dirty or event.flag_staged:
                    dirty_paths.append(event.path)
        if revision_event is None:
            raise LoreAdapterError("Lore status returned no revision state")
        if branch and revision_event.branch_name != branch:
            raise LoreAdapterError(
                f"Current Lore branch is {revision_event.branch_name!r}, not {branch!r}"
            )
        if not revision_event.remote_available or not revision_event.remote_authorized:
            raise LoreAdapterError("Lore remote is unavailable or unauthorized")
        return RemoteHeads(
            branch=revision_event.branch_name,
            local_revision=_hex(revision_event.revision_local),
            remote_revision=_hex(revision_event.revision_remote),
            local_ahead=bool(revision_event.is_local_ahead),
            remote_ahead=bool(revision_event.is_remote_ahead),
            dirty_paths=tuple(sorted(set(dirty_paths))),
        )

    @staticmethod
    def _raise_preflight_conflict(heads: RemoteHeads, *, for_sync: bool) -> None:
        if heads.dirty_paths:
            raise LoreRemoteConflict(RemoteConflict.DIRTY_WORKTREE, heads)
        if heads.local_ahead and heads.remote_ahead:
            raise LoreRemoteConflict(RemoteConflict.DIVERGED, heads)
        if for_sync and heads.local_ahead:
            raise LoreRemoteConflict(RemoteConflict.LOCAL_AHEAD, heads)
        if not for_sync and heads.remote_ahead:
            raise LoreRemoteConflict(RemoteConflict.STALE_REMOTE_HEAD, heads)

    def push(
        self, project: ProjectRecord, session: RemoteSession, *, branch: str = ""
    ) -> RemoteTransferOutcome:
        heads = self.remote_heads(project, session, branch=branch)
        self._raise_preflight_conflict(heads, for_sync=False)
        if not heads.local_ahead:
            return RemoteTransferOutcome(
                revision=heads.remote_revision or heads.local_revision,
                changed=False,
            )
        try:
            events = self._lore.branch_push(
                self._remote_globals(project.root_path, session),
                self._types["branch_push"](
                    branch=branch,
                    # Binary project files must never opt into server-side
                    # head rewriting when another writer moved the branch.
                    fast_forward_merge=False,
                ),
            ).collect()
        except Exception:
            refreshed = self.remote_heads(project, session, branch=branch)
            if refreshed.remote_ahead:
                raise LoreRemoteConflict(RemoteConflict.STALE_REMOTE_HEAD, refreshed)
            raise
        for event in events:
            if isinstance(event, self._types["push_event"]):
                return RemoteTransferOutcome(_hex(event.local_revision), True)
        return RemoteTransferOutcome(heads.local_revision, True)

    def sync(
        self, project: ProjectRecord, session: RemoteSession, *, branch: str = ""
    ) -> RemoteTransferOutcome:
        heads = self.remote_heads(project, session, branch=branch)
        self._raise_preflight_conflict(heads, for_sync=True)
        if not heads.remote_ahead:
            return RemoteTransferOutcome(heads.local_revision, False)
        if not heads.remote_revision:
            raise LoreAdapterError("Remote branch has no authoritative revision")
        # Pin the observed remote hash. A later remote push cannot turn this
        # operation into an implicit merge with an unreviewed binary revision.
        events = self._lore.revision_sync(
            self._remote_globals(project.root_path, session),
            self._types["sync"](
                revision=heads.remote_revision,
                forward_changes=False,
                reset=False,
            ),
        ).collect()
        for event in events:
            if isinstance(event, self._types["sync_event"]):
                if event.flag_merge or event.flag_conflict:
                    raise LoreRemoteConflict(RemoteConflict.DIVERGED, heads)
                return RemoteTransferOutcome(_hex(event.revision), True)
        raise LoreAdapterError("Lore sync completed without a revision event")

    def shutdown(self) -> None:
        if self._loaded:
            try:
                self._lore.shutdown()
            except Exception:
                pass
