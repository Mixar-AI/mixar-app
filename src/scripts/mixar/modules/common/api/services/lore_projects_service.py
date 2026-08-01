# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Backend control-plane client for isolated Lore collaboration."""

from dataclasses import replace

from ....project_versioning.core.models import ProjectRecord, RemoteSession
from ..constants import APIModule
from ..response import APIResponse
from .base_service import BaseService


def _data(response: APIResponse):
    payload = response.data
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


class LoreProjectsService(BaseService):
    @property
    def module(self) -> APIModule:
        return APIModule.LORE

    def create_project(
        self, project: ProjectRecord, *, name: str, team_id: str | None = None
    ) -> dict:
        response = self.post(
            "projects",
            json={
                "client_project_id": project.project_id,
                "repository_id": project.repository_id.replace("-", ""),
                "name": name,
                "team_id": team_id,
                "default_branch": project.default_branch,
            },
        )
        return dict(_data(response) or {})

    def list_projects(self) -> list[dict]:
        return list(_data(self.get("projects")) or [])

    def bootstrap(
        self,
        project: ProjectRecord,
        *,
        client_instance_id: str,
        branch: str | None = None,
    ) -> RemoteSession:
        response = self.post(
            f"projects/{project.control_project_id}/collaboration/bootstrap",
            json={"client_instance_id": client_instance_id, "branch": branch},
        )
        data = dict(_data(response) or {})
        instance = data["instance"]
        credential = data["credential"]
        lease = data["edit_lease"]
        session = data["session"]
        return RemoteSession(
            repository_url=instance["remote_url"],
            token=credential["token"],
            token_type=credential.get("token_type", "lore"),
            identity_id=project.identity_id,
            resource=f"urc-{instance['repository_id']}",
            user_id=str(session["user_id"]),
            control_project_id=str(project.control_project_id),
            branch=session["branch"],
            lease_id=lease["lease_id"],
            lease_token=lease["lease_token"],
            lease_expires_at=lease["expires_at"],
            refresh_after=credential["refresh_after"],
            remote_revision=data["branch"].get("head_revision"),
        )

    def renew(self, session: RemoteSession) -> RemoteSession:
        response = self.post(
            f"projects/{session.control_project_id}/collaboration/renew",
            json={
                "lease_id": session.lease_id,
                "lease_token": session.lease_token,
            },
        )
        data = dict(_data(response) or {})
        credential = data["credential"]
        lease = data["edit_lease"]
        return replace(
            session,
            token=credential["token"],
            token_type=credential.get("token_type", "lore"),
            lease_token=lease["lease_token"],
            lease_expires_at=lease["expires_at"],
            refresh_after=credential["refresh_after"],
        )

    def release(self, session: RemoteSession) -> None:
        self.post(
            f"projects/{session.control_project_id}/collaboration/release",
            json={
                "lease_id": session.lease_id,
                "lease_token": session.lease_token,
            },
        )

    def record_revision(
        self,
        project: ProjectRecord,
        *,
        revision: str,
        base_revision: str | None,
        source: str,
        message: str,
    ) -> dict:
        response = self.post(
            f"projects/{project.control_project_id}/revisions",
            json={
                "branch": project.default_branch,
                "revision": revision,
                "base_revision": base_revision,
                "source": source,
                "message": message,
                "semantic_summary": {},
            },
        )
        return dict(_data(response) or {})


_service: LoreProjectsService | None = None


def get_lore_projects_service() -> LoreProjectsService:
    global _service
    if _service is None:
        _service = LoreProjectsService()
    return _service
