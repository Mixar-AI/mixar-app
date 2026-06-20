# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Brush API Service.

Handles brush texture generation via the image-generation API module.
Endpoint: POST /api/v1/image-generation/generate-brush (multipart/form-data)
"""

from typing import Callable, List, Optional

from ....auth.core.auth import get_access_token
from ..constants import APIModule, BRUSH_GEN_TIMEOUT
from ..exceptions import AuthenticationError
from ..request_queue import AsyncResponse
from ..response import APIResponse
from .base_service import BaseService


def _require_auth() -> None:
    """Raise AuthenticationError if no access token is available."""
    token = get_access_token()
    if not token:
        raise AuthenticationError(
            message="Authentication required. Please login first.",
            status_code=401,
        )


def _build_files(
    prompt: str,
    model_name: str,
    reference_image: Optional[bytes] = None,
) -> List[tuple]:
    """Build multipart form-data file tuples for the brush generation API.

    Args:
        prompt: Text description for the brush texture.
        model_name: Model identifier ("flash" or "pro").
        reference_image: Optional PNG bytes of a reference image.

    Returns:
        List of (field, (filename, data, content_type)) tuples.
    """
    files = [
        ("prompt", (None, prompt)),
        ("model_name", (None, model_name)),
    ]

    if reference_image:
        files.append(
            ("reference_image", ("reference.png", reference_image, "image/png"))
        )

    return files


class BrushService(BaseService):
    """
    Brush service for AI brush texture generation.

    Endpoints:
    - POST /generate-brush - Generate brush texture with AI
    """

    @property
    def module(self) -> APIModule:
        return APIModule.IMAGEGEN

    # ========================================================================
    # SYNC METHODS
    # ========================================================================

    def generate(
        self,
        prompt: str,
        model_name: str = "flash",
        reference_image: Optional[bytes] = None,
    ) -> APIResponse:
        """
        Generate a brush texture using AI.

        Args:
            prompt: Text description for the brush texture.
            model_name: Model to use ("flash" or "pro").
            reference_image: Optional PNG bytes of a reference image.

        Returns:
            APIResponse with generated image URL and color.

        Raises:
            AuthenticationError: If no access token is available.
        """
        _require_auth()

        files = _build_files(prompt, model_name, reference_image)
        return self.post("generate-brush", files=files, timeout=BRUSH_GEN_TIMEOUT)

    # ========================================================================
    # ASYNC METHODS
    # ========================================================================

    def generate_async(
        self,
        prompt: str,
        model_name: str = "flash",
        reference_image: Optional[bytes] = None,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Generate a brush texture using AI asynchronously.

        Args:
            prompt: Text description for the brush texture.
            model_name: Model to use ("flash" or "pro").
            reference_image: Optional PNG bytes of a reference image.
            on_success: Callback for successful response.
            on_error: Callback for errors.
            on_complete: Callback with full AsyncResponse.

        Returns:
            Request ID for tracking.

        Raises:
            AuthenticationError: If no access token is available.
        """
        _require_auth()

        files = _build_files(prompt, model_name, reference_image)
        return self.post_async(
            "generate-brush",
            files=files,
            timeout=BRUSH_GEN_TIMEOUT,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )


# Singleton instance
_brush_service: Optional[BrushService] = None


def get_brush_service() -> BrushService:
    """Get the global BrushService instance."""
    global _brush_service
    if _brush_service is None:
        _brush_service = BrushService()
    return _brush_service
