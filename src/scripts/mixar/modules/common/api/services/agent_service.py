# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Agent settings over HTTP: BYOK credentials and the provider/model catalog.

Settings are NOT agent traffic. They rode the agent WebSocket for a while, and
``agent_rpc.get_client()`` raises the moment that socket is absent or
un-handshaken — so the post-login settings fetch, which fires on the same tick
that merely *initiates* the connection, failed on every cold start and the AI
Provider Settings dialog showed "Not configured" over a credential that was
stored and in use. The client needs settings before the agent exists, which is
what plain HTTP gives it.

The backend serves both surfaces (``modules/agent/api/routes/agent_settings.py``
and the ``byok.*`` / ``credentials.*`` WebSocket commands); this client uses HTTP
only. Chat, input, cancel, streaming and replay stay on the socket via
``common/agent_rpc``.
"""

from typing import Optional

from ..constants import APIModule
from ..response import APIResponse
from .base_service import BaseService


class AgentService(BaseService):
    """Endpoints under /api/v1/agent (settings only)."""

    @property
    def module(self) -> APIModule:
        return APIModule.AGENT

    # --- Model catalog -----------------------------------------------------

    def list_models(self, etag: Optional[str] = None) -> APIResponse:
        """GET /agent/models — providers + models for the dropdowns.

        Pass the stored ``etag`` to revalidate: an unchanged catalog answers 304
        with an empty body, which is the caller's signal to keep what it has.

        NOTE for callers: ``APIResponse.success`` is ``response.ok``, which is
        True at 304 — check the status code BEFORE the success flag or you will
        swap a live catalog for an empty payload.
        """
        headers = {"If-None-Match": etag} if etag else None
        return self.get("models", headers=headers)

    # --- BYOK credentials --------------------------------------------------

    def get_credentials(self) -> APIResponse:
        """GET /agent/credentials — current BYOK state for the user."""
        return self.get("credentials")

    def save_credentials_all(
        self,
        provider: str,
        model: str,
        api_key: Optional[str],
        base_url: Optional[str] = None,
        supports_vision: Optional[bool] = None,
    ) -> APIResponse:
        """PUT /agent/byok — upsert BYOK config across all agent roles.

        Uses the backend's single-value wrapper, which fans one
        provider/model/key out to the default + per-agent roles and returns the
        same {items, byok_active} shape as GET /agent/credentials.

        The server validates the key with the provider (200ms-15s) before
        storing. Atomic: on any failure the previous state is preserved.

        ``base_url`` / ``supports_vision`` are sent only when provided (the
        "local" provider registering its relay target) — omitting them keeps the
        payload byte-identical for older backends.
        """
        payload = {"provider": provider, "model": model}
        if api_key is not None:
            payload["api_key"] = api_key
        if base_url is not None:
            payload["base_url"] = base_url
        if supports_vision is not None:
            payload["supports_vision"] = bool(supports_vision)
        return self.put("byok", json=payload)

    def delete_credentials_all(self) -> APIResponse:
        """DELETE /agent/credentials/all — remove BYOK config. Always 200."""
        return self.delete("credentials/all")


_agent_service = None


def get_agent_service():
    global _agent_service
    if _agent_service is None:
        _agent_service = AgentService()
    return _agent_service
