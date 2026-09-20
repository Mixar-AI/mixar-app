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

    # --- Hosted model preference -------------------------------------------
    #
    # The pick is a STORED PREFERENCE, resolved server-side when a turn starts.
    # `/agent/chat` and `/agent/input` carry no model field — do not add one.
    #
    # The desktop client saves exactly one pick, under ``role="default"``; the
    # backend fans it out. The per-agent roles (chat, orchestrator, worker, …)
    # exist in the API but have no desktop surface.

    def get_model_preference(self) -> APIResponse:
        """GET /agent/model-preference — the account's saved pick.

        ``Cache-Control: no-store`` server-side and always 200 for an authed
        user; the response carries ``byok_active`` alongside the items, which is
        what disables the picker. Never cached to disk — it is per-account and
        cheap.
        """
        return self.get("model-preference")

    def put_model_preference(
        self,
        provider: str,
        model: str,
        role: str = "default",
        thinking_level: Optional[str] = None,
    ) -> APIResponse:
        """PUT /agent/model-preference — save the pick.

        ``thinking_level`` is omitted from the payload entirely when None (the
        model's own default), so the bytes stay identical for a backend that
        predates the field — the same treatment `save_credentials_all` gives
        base_url / supports_vision.

        400 = ineligible model or a thinking level the model does not offer
        (message prefixed "Model not available: " for model errors);
        422 = schema, e.g. a BYOK-only provider.
        """
        payload = {"provider": provider, "model": model, "role": role}
        if thinking_level is not None:
            payload["thinking_level"] = thinking_level
        return self.put("model-preference", json=payload)

    def delete_model_preference(self, role: str = "default") -> APIResponse:
        """DELETE /agent/model-preference/{role} — 200, or 404 if unset.

        The role is not validated server-side; an unknown one simply 404s.
        """
        return self.delete(f"model-preference/{role}")

    def delete_model_preferences(self) -> APIResponse:
        """DELETE /agent/model-preference — clear every role. `{"removed": n}`."""
        return self.delete("model-preference")


_agent_service = None


def get_agent_service():
    global _agent_service
    if _agent_service is None:
        _agent_service = AgentService()
    return _agent_service
