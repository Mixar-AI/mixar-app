# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blender-main-thread lifecycle bridge for the Lore checkpoint worker."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace
import json
import os
from pathlib import Path
from uuid import uuid4

import bpy
from bpy.app.handlers import persistent

from mixar.config.config import get_config
from mixar.config.logging_config import get_logger
from mixar.modules.project_versioning.constants import (
    RESULT_TIMER_INTERVAL_SECONDS,
    SHUTDOWN_TIMEOUT_SECONDS,
)

from .availability import detect
from .checkpoint_service import CheckpointService
from .models import (
    Availability,
    CheckpointRequest,
    CheckpointResult,
    CheckpointState,
    ProjectRecord,
    ProjectState,
    RemoteCloneRequest,
    RemoteCreateRequest,
    RemoteOperation,
    RemoteOperationResult,
    RemotePushRequest,
    RemoteResultState,
    RemoteSession,
    RemoteSyncRequest,
)
from .project_store import ProjectStore, ProjectStoreError

logger = get_logger(__name__)

_service: CheckpointService | None = None
_store: ProjectStore | None = None
_epoch = 0
_registered = False
_client_instance_id = str(uuid4())
_remote_session: RemoteSession | None = None
_remote_context: dict[str, dict] = {}
_status = {
    "availability": Availability.BUILD_DISABLED.value,
    "state": ProjectState.UNLINKED.value,
    "last_revision": None,
    "pending": 0,
    "error": None,
    "filepath": None,
    "collaboration": "disconnected",
    "remote_operation": None,
    "remote_revision": None,
    "lease_expires_at": None,
}


def _build_enabled() -> bool:
    return bool(get_config().get("lore_pilot", {}).get("enabled", False))


def _user_data_dir() -> str:
    try:
        return bpy.utils.user_resource("CONFIG", path="mixar", create=True)
    except Exception:
        return str(Path.home() / ".mixar")


def get_status() -> dict:
    return dict(_status)


def _control_service():
    from mixar.modules.common.api.services.lore_projects_service import (
        get_lore_projects_service,
    )

    return get_lore_projects_service()


def _current_project() -> ProjectRecord | None:
    if _store is None:
        return None
    filepath = _current_filepath()
    return _store.load_for_file(filepath) if filepath else None


def _set_session(session: RemoteSession | None) -> None:
    global _remote_session
    _remote_session = session
    _status["collaboration"] = "connected" if session else "disconnected"
    _status["lease_expires_at"] = session.lease_expires_at if session else None
    _status["remote_revision"] = session.remote_revision if session else None


def _renew_session_if_due() -> tuple[bool, str]:
    if _remote_session is None:
        return False, "Start collaboration first"
    try:
        refresh_at = datetime.fromisoformat(_remote_session.refresh_after.replace("Z", "+00:00"))
        if datetime.now(timezone.utc) >= refresh_at:
            _set_session(_control_service().renew(_remote_session))
    except Exception as exc:
        _set_state(ProjectState.ERROR, error=f"Collaboration lease renewal failed: {exc}")
        return False, str(exc)
    return True, "Collaboration lease is active"


def share_current_project(*, name: str, team_id: str | None = None) -> tuple[bool, str]:
    if _store is None or _service is None:
        return False, "Lore collaboration is unavailable"
    filepath = _current_filepath()
    if not filepath:
        return False, "Save the Blender project before sharing"
    if (Path(filepath).resolve().parent / ".lore" / "config.toml").is_file():
        current = _store.load_for_file(filepath, require_enabled=False)
        if current is None or not current.remote:
            return False, "This local Lore history must be migrated before it can be shared"
    try:
        local = _store.enable(filepath)
        response = _control_service().create_project(
            local, name=name.strip() or Path(filepath).stem, team_id=team_id or None
        )
        project = _store.mark_remote(filepath, control_project_id=str(response["id"]))
        session = _control_service().bootstrap(
            project,
            client_instance_id=_client_instance_id,
            branch=project.default_branch,
        )
        _set_session(session)
        request_id = str(uuid4())
        _remote_context[request_id] = {"action": "create"}
        if not _service.submit_remote(
            RemoteCreateRequest(
                request_id=request_id, project=project, session=session, epoch=_epoch
            )
        ):
            return False, "Lore worker is shutting down"
        _status["remote_operation"] = RemoteOperation.CREATE.value
        return True, "Shared project created; remote initialization queued"
    except Exception as exc:
        return False, str(exc)


def start_collaboration() -> tuple[bool, str]:
    project = _current_project()
    if project is None or not project.remote or not project.control_project_id:
        return False, "This project has not been shared"
    try:
        _set_session(
            _control_service().bootstrap(
                project,
                client_instance_id=_client_instance_id,
                branch=project.default_branch,
            )
        )
        return True, "Exclusive edit lease acquired"
    except Exception as exc:
        return False, str(exc)


def stop_collaboration() -> tuple[bool, str]:
    if _remote_session is None:
        return True, "Collaboration is already stopped"
    try:
        _control_service().release(_remote_session)
    except Exception as exc:
        return False, str(exc)
    _set_session(None)
    return True, "Edit lease released"


def _submit_remote(operation: RemoteOperation) -> tuple[bool, str]:
    project = _current_project()
    if project is None or not project.remote or _service is None:
        return False, "Open a shared project first"
    ok, message = _renew_session_if_due()
    if not ok or _remote_session is None:
        return False, message
    if bool(getattr(bpy.data, "is_dirty", True)):
        return False, "Save the Blender file before transferring revisions"
    request_id = str(uuid4())
    if operation == RemoteOperation.PUSH:
        request = RemotePushRequest(
            request_id=request_id, project=project, session=_remote_session, epoch=_epoch
        )
    else:
        request = RemoteSyncRequest(
            request_id=request_id, project=project, session=_remote_session, epoch=_epoch
        )
    _remote_context[request_id] = {"action": operation.value}
    if not _service.submit_remote(request):
        return False, "Lore worker is shutting down"
    _status["remote_operation"] = operation.value
    return True, f"{operation.value.title()} queued"


def push_current_project() -> tuple[bool, str]:
    return _submit_remote(RemoteOperation.PUSH)


def sync_current_project() -> tuple[bool, str]:
    return _submit_remote(RemoteOperation.SYNC)


def join_project(*, control_project_id: str, destination: str) -> tuple[bool, str]:
    if _service is None:
        return False, "Lore collaboration is unavailable"
    root = Path(destination).expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        return False, "Choose an empty destination folder"
    try:
        projects = _control_service().list_projects()
        remote = next(item for item in projects if str(item["id"]) == control_project_id)
        identity_id = str(uuid4())
        project = ProjectRecord(
            project_id=str(remote["client_project_id"]),
            repository_id=str(remote["lore_repository_id"]),
            identity_id=identity_id,
            root_path=str(root),
            blend_path=str(root / "pending.blend"),
            default_branch=str(remote.get("default_branch", "main")),
            control_project_id=control_project_id,
            remote=True,
        )
        session = _control_service().bootstrap(
            project, client_instance_id=_client_instance_id, branch=project.default_branch
        )
        _set_session(session)
        request_id = str(uuid4())
        _remote_context[request_id] = {
            "action": "clone",
            "destination": str(root),
            "identity_id": identity_id,
        }
        root.mkdir(parents=True, exist_ok=True)
        if not _service.submit_remote(
            RemoteCloneRequest(
                request_id=request_id,
                repository_path=str(root),
                session=session,
                epoch=_epoch,
            )
        ):
            return False, "Lore worker is shutting down"
        _status["remote_operation"] = RemoteOperation.CLONE.value
        return True, "Project clone queued"
    except (KeyError, StopIteration) as exc:
        return False, "Shared project was not found for your team"
    except Exception as exc:
        return False, str(exc)


def _set_state(state: ProjectState, *, error: str | None = None) -> None:
    _status["state"] = state.value
    _status["error"] = error


def _current_filepath() -> str:
    return str(getattr(bpy.data, "filepath", "") or "")


def _capture_metadata() -> dict:
    scenes = []
    for scene in getattr(bpy.data, "scenes", ()):
        history_id = ""
        try:
            history_id = str(scene.get("mixar_op_history_id", ""))
        except Exception:
            pass
        scenes.append({"name": str(scene.name), "history_id": history_id})
    return {
        "mixar_version": get_config().get("app_info", {}).get("version", "unknown"),
        "blender_version": ".".join(str(v) for v in bpy.app.version),
        "scenes": scenes,
    }


def enqueue_checkpoint(*, source: str, message: str) -> bool:
    global _service
    if _service is None or _store is None:
        return False
    filepath = _current_filepath()
    project = _store.load_for_file(filepath)
    if project is None:
        _set_state(ProjectState.UNLINKED)
        return False
    if project.remote:
        if (
            _remote_session is None
            or _remote_session.control_project_id != project.control_project_id
        ):
            _set_state(ProjectState.ERROR, error="Acquire the project edit lease before saving")
            return False
        renewed, error = _renew_session_if_due()
        if not renewed:
            _set_state(ProjectState.ERROR, error=error)
            return False
    try:
        stat = os.stat(filepath)
        relative = str(Path(filepath).resolve().relative_to(Path(project.root_path)))
    except (OSError, ValueError) as exc:
        _set_state(ProjectState.ERROR, error=str(exc))
        return False

    request = CheckpointRequest(
        request_id=str(uuid4()),
        project=project,
        filepath=str(Path(filepath).resolve()),
        relative_blend_path=relative,
        source=source,
        message=message,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        epoch=_epoch,
        captured_at=datetime.now(timezone.utc).isoformat(),
        metadata=_capture_metadata(),
    )
    accepted = _service.submit(request)
    if accepted:
        _status["pending"] += 1
        _status["filepath"] = request.filepath
        _set_state(ProjectState.CHECKPOINTING)
    return accepted


def enable_current_project() -> tuple[bool, str]:
    if _status["availability"] != Availability.AVAILABLE.value:
        return False, f"Lore is unavailable: {_status['availability']}"
    if _store is None:
        return False, "Project store is not initialized"
    filepath = _current_filepath()
    try:
        _store.enable(filepath)
    except ProjectStoreError as exc:
        return False, str(exc)
    if enqueue_checkpoint(source="enable", message="Enable Mixar project versioning"):
        return True, "Project versioning enabled; initial checkpoint queued"
    return False, "Could not queue the initial checkpoint"


def disable_current_project() -> tuple[bool, str]:
    if _store is None or not _store.disable(_current_filepath()):
        return False, "This file is not an enabled Mixar Lore project"
    _set_state(ProjectState.UNLINKED)
    return True, "Project versioning disabled; existing history was preserved"


@persistent
def _load_pre(_unused) -> None:
    global _epoch
    _epoch += 1
    _status["filepath"] = None
    _set_state(ProjectState.UNLINKED)


@persistent
def _load_post(_unused) -> None:
    if _store is None:
        return
    filepath = _current_filepath()
    project = _store.load_for_file(filepath) if filepath else None
    _status["filepath"] = filepath or None
    _set_state(ProjectState.READY if project else ProjectState.UNLINKED)
    if project is None or _remote_session is None:
        _status["collaboration"] = "disconnected"
    elif _remote_session.control_project_id != project.control_project_id:
        _set_session(None)


@persistent
def _save_post(_unused) -> None:
    if _status["availability"] == Availability.AVAILABLE.value:
        enqueue_checkpoint(source="manual", message="Mixar manual save")


def _drain_results() -> float | None:
    if not _registered or _service is None:
        return None
    for result in _service.drain_results():
        if isinstance(result, CheckpointResult):
            _status["pending"] = max(0, int(_status["pending"]) - 1)
            if result.epoch != _epoch or result.filepath != _current_filepath():
                continue
            if result.state == CheckpointState.SUCCEEDED:
                _status["last_revision"] = result.revision
                _set_state(ProjectState.READY)
                project = _current_project()
                if project is not None and project.remote and _remote_session is not None:
                    _submit_remote(RemoteOperation.PUSH)
            elif result.state == CheckpointState.SUPERSEDED:
                _set_state(ProjectState.READY)
            elif result.state == CheckpointState.FAILED:
                _set_state(ProjectState.ERROR, error=result.error)
                logger.warning("Lore checkpoint failed: %s", result.error)
            continue

        if not isinstance(result, RemoteOperationResult) or result.epoch != _epoch:
            continue
        context = _remote_context.pop(result.request_id, {})
        _status["remote_operation"] = None
        if result.state == RemoteResultState.CONFLICT:
            _set_state(
                ProjectState.ERROR,
                error=f"Remote {result.operation.value} conflict: {result.conflict.value}",
            )
            continue
        if result.state == RemoteResultState.FAILED:
            _set_state(ProjectState.ERROR, error=result.error)
            logger.warning("Lore remote operation failed: %s", result.error)
            continue
        if result.operation == RemoteOperation.CREATE:
            enqueue_checkpoint(source="share", message="Create shared Mixar project")
        elif result.operation == RemoteOperation.CLONE:
            try:
                root = Path(context["destination"])
                manifest = json.loads(
                    (root / ".mixar" / "project.json").read_text(encoding="utf-8")
                )
                blend = root / manifest["primary_blend_path"]
                if _store is None:
                    raise ProjectStoreError("Project store is unavailable")
                _store.attach_remote_clone(
                    str(blend), identity_id=str(context["identity_id"])
                )
                _status["filepath"] = str(blend)
                _set_state(ProjectState.READY)
                bpy.ops.wm.open_mainfile(filepath=str(blend))
            except Exception as exc:
                _set_state(ProjectState.ERROR, error=f"Clone attach failed: {exc}")
        elif result.operation == RemoteOperation.PUSH and result.revision:
            project = _current_project()
            if project is not None and _remote_session is not None:
                try:
                    _control_service().record_revision(
                        project,
                        revision=result.revision,
                        base_revision=_remote_session.remote_revision,
                        source="manual",
                        message="Mixar Blender save",
                    )
                    _set_session(replace(_remote_session, remote_revision=result.revision))
                    _set_state(ProjectState.READY)
                except Exception as exc:
                    _set_state(ProjectState.ERROR, error=f"Revision registration failed: {exc}")
        elif result.operation == RemoteOperation.SYNC:
            if _remote_session is not None:
                _set_session(replace(_remote_session, remote_revision=result.revision))
            _set_state(
                ProjectState.READY,
                error=(
                    "Remote changes downloaded; reopen the project to load them"
                    if result.revision
                    else None
                ),
            )
    if _remote_session is not None:
        _renew_session_if_due()
    return RESULT_TIMER_INTERVAL_SECONDS


def register() -> None:
    global _registered, _service, _store
    if _registered:
        return
    _registered = True
    availability = detect(build_enabled=_build_enabled())
    _status["availability"] = availability.value
    _store = ProjectStore(user_data_dir=_user_data_dir())
    if availability == Availability.AVAILABLE:
        _service = CheckpointService()
        _service.start()
    for collection, callback in (
        (bpy.app.handlers.load_pre, _load_pre),
        (bpy.app.handlers.load_post, _load_post),
        (bpy.app.handlers.save_post, _save_post),
    ):
        if callback not in collection:
            collection.append(callback)
    if not bpy.app.timers.is_registered(_drain_results):
        bpy.app.timers.register(
            _drain_results,
            first_interval=RESULT_TIMER_INTERVAL_SECONDS,
            persistent=True,
        )
    _load_post(None)


def shutdown() -> None:
    global _service
    if _remote_session is not None:
        try:
            _control_service().release(_remote_session)
        except Exception as exc:
            logger.warning("Could not release Lore edit lease during shutdown: %s", exc)
        _set_session(None)
    if _service is not None:
        _set_state(ProjectState.SHUTTING_DOWN)
        _service.shutdown(SHUTDOWN_TIMEOUT_SECONDS)
        _service = None


def unregister() -> None:
    global _registered
    if not _registered:
        return
    _registered = False
    for collection, callback in (
        (bpy.app.handlers.load_pre, _load_pre),
        (bpy.app.handlers.load_post, _load_post),
        (bpy.app.handlers.save_post, _save_post),
    ):
        if callback in collection:
            collection.remove(callback)
    if bpy.app.timers.is_registered(_drain_results):
        bpy.app.timers.unregister(_drain_results)
    shutdown()
