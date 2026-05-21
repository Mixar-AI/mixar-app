# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Base service class for API modules.

Provides abstract base for service-specific implementations
with both sync and async request methods.
"""

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional

from ..client import HTTPClient, get_http_client
from ..constants import API_VERSION, APIModule
from ..request_queue import AsyncResponse
from ..response import APIResponse


class BaseService(ABC):
    """
    Abstract base class for API service modules.

    Each API module (agent, auth, images) extends this class
    to implement module-specific endpoints with both sync
    and async variants.
    """

    def __init__(self, client: Optional[HTTPClient] = None):
        """
        Initialize service with HTTP client.

        Args:
            client: HTTPClient instance (defaults to global singleton)
        """
        self._client = client or get_http_client()

    @property
    @abstractmethod
    def module(self) -> APIModule:
        """Get the API module this service handles."""
        pass

    @property
    def base_path(self) -> str:
        """Get the base path for this service's endpoints."""
        return f"api/{API_VERSION}/{self.module.value}"

    def _endpoint(self, path: str) -> str:
        """Build full endpoint path."""
        if not path:
            return self.base_path
        path = path.lstrip("/")
        return f"{self.base_path}/{path}"

    # ========================================================================
    # SYNC METHODS
    # ========================================================================

    def get(self, path: str = "", **kwargs) -> APIResponse:
        """Make a GET request to this service."""
        return self._client.get(self._endpoint(path), **kwargs)

    def post(self, path: str = "", **kwargs) -> APIResponse:
        """Make a POST request to this service."""
        return self._client.post(self._endpoint(path), **kwargs)

    def put(self, path: str = "", **kwargs) -> APIResponse:
        """Make a PUT request to this service."""
        return self._client.put(self._endpoint(path), **kwargs)

    def patch(self, path: str = "", **kwargs) -> APIResponse:
        """Make a PATCH request to this service."""
        return self._client.patch(self._endpoint(path), **kwargs)

    def delete(self, path: str = "", **kwargs) -> APIResponse:
        """Make a DELETE request to this service."""
        return self._client.delete(self._endpoint(path), **kwargs)

    # ========================================================================
    # ASYNC METHODS
    # ========================================================================

    def get_async(
        self,
        path: str = "",
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
        **kwargs,
    ) -> str:
        """Make an async GET request to this service."""
        return self._client.get_async(
            self._endpoint(path),
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
            **kwargs,
        )

    def post_async(
        self,
        path: str = "",
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
        **kwargs,
    ) -> str:
        """Make an async POST request to this service."""
        return self._client.post_async(
            self._endpoint(path),
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
            **kwargs,
        )

    def put_async(
        self,
        path: str = "",
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
        **kwargs,
    ) -> str:
        """Make an async PUT request to this service."""
        return self._client.put_async(
            self._endpoint(path),
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
            **kwargs,
        )

    def patch_async(
        self,
        path: str = "",
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
        **kwargs,
    ) -> str:
        """Make an async PATCH request to this service."""
        return self._client.patch_async(
            self._endpoint(path),
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
            **kwargs,
        )

    def delete_async(
        self,
        path: str = "",
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
        **kwargs,
    ) -> str:
        """Make an async DELETE request to this service."""
        return self._client.delete_async(
            self._endpoint(path),
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
            **kwargs,
        )

    def fire_and_forget_post(self, path: str = "", **kwargs) -> str:
        """Fire-and-forget POST request."""
        return self._client.fire_and_forget("POST", self._endpoint(path), **kwargs)
