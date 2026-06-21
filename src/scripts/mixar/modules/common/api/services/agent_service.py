# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Agent API Service.

Handles /api/v1/agent endpoints for AI/ML features.
"""

from typing import Any, Callable, Dict, Optional

from ..constants import APIModule
from ..request_queue import AsyncResponse
from ..response import APIResponse
from .base_service import BaseService


class AgentService(BaseService):
    """
    Agent service for AI/ML operations.

    Endpoints:
    - GET /context-script - Get context collector script
    - POST /process - Process agent request
    - GET /models - List available models
    """

    @property
    def module(self) -> APIModule:
        return APIModule.AGENT

    # ========================================================================
    # SYNC METHODS
    # ========================================================================

    def get_context_script(self) -> APIResponse:
        """
        Fetch the context collector script from server.

        Returns:
            APIResponse with script content
        """
        return self.get("context-script")

    def process(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """
        Submit a request to the agent for processing.

        Args:
            prompt: User prompt/request
            context: Context data from Blender
            model: Model to use (optional)
            options: Additional options

        Returns:
            APIResponse with processing result
        """
        payload = {"prompt": prompt}
        if context:
            payload["context"] = context
        if model:
            payload["model"] = model
        if options:
            payload["options"] = options

        return self.post("process", json=payload)

    def list_models(self) -> APIResponse:
        """
        List available agent models.

        Returns:
            APIResponse with list of models
        """
        return self.get("models")

    # ========================================================================
    # BYOK — Bring-Your-Own-Key credentials
    # ========================================================================

    def get_credentials(self) -> APIResponse:
        """GET /agent/credentials — fetch current BYOK state for the user."""
        return self.get("credentials")

    def save_credentials_all(
        self,
        provider: str,
        model: str,
        api_key: str,
    ) -> APIResponse:
        """PUT /agent/byok — upsert BYOK config across all agent roles.

        Uses the backend's single-value BYOK wrapper, which fans one
        provider/model/key out to the default + per-agent roles and returns
        the same {items, byok_active} shape as GET /agent/credentials.

        Server validates the key with the provider (200ms–15s) before storing.
        Atomic: on any failure, previous state (if any) is preserved.
        """
        payload = {
            "provider": provider,
            "model": model,
            "api_key": api_key,
        }
        return self.put("byok", json=payload)

    def delete_credentials_all(self) -> APIResponse:
        """DELETE /agent/credentials/all — remove BYOK config. Always 200."""
        return self.delete("credentials/all")

    # ========================================================================
    # ASYNC METHODS
    # ========================================================================

    def get_context_script_async(
        self,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Fetch the context collector script asynchronously.

        Args:
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking
        """
        return self.get_async(
            "context-script",
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    def process_async(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Submit a request to the agent for processing asynchronously.

        Args:
            prompt: User prompt/request
            context: Context data from Blender
            model: Model to use (optional)
            options: Additional options
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking
        """
        payload = {"prompt": prompt}
        if context:
            payload["context"] = context
        if model:
            payload["model"] = model
        if options:
            payload["options"] = options

        return self.post_async(
            "process",
            json=payload,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    def list_models_async(
        self,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        List available agent models asynchronously.

        Args:
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking
        """
        return self.get_async(
            "models",
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )


# Singleton instance
_agent_service: Optional[AgentService] = None


def get_agent_service() -> AgentService:
    """Get the global AgentService instance."""
    global _agent_service
    if _agent_service is None:
        _agent_service = AgentService()
    return _agent_service
