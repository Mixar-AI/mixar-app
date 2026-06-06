# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
ImageGen API Service.

Handles dynamic image generation using the unified API.
Endpoints:
- GET /models: List available models with capabilities
- GET /styles: List available style presets
- POST /generate: Unified generation endpoint
"""

from typing import Callable, List, Optional

from mixar.config.logging_config import get_logger

from ....auth.core.auth import get_access_token
from ..constants import APIModule
from ..exceptions import AuthenticationError
from ..request_queue import AsyncResponse
from ..response import APIResponse
from .base_service import BaseService

logger = get_logger(__name__)

# AI image generation can take 60+ seconds
IMAGEGEN_TIMEOUT = 120.0


def _require_auth() -> None:
    """Raise AuthenticationError if no access token is available."""
    token = get_access_token()
    if not token:
        raise AuthenticationError(
            message="Authentication required. Please login first.",
            status_code=401,
        )


class ImageGenService(BaseService):
    """
    ImageGen service for dynamic AI image generation.

    Provides:
    - Dynamic model listing with capabilities
    - Dynamic style listing
    - Unified generation endpoint
    """

    @property
    def module(self) -> APIModule:
        return APIModule.IMAGEGEN

    # ========================================================================
    # MODEL AND STYLE LISTING METHODS
    # ========================================================================

    def get_models(self) -> APIResponse:
        """
        Get list of available image generation models.

        Returns:
            APIResponse with data.models list containing:
            - name: Model identifier (e.g., "flash", "pro")
            - display_name: UI display name (e.g., "Gemini 2.5 Flash")
            - credit_cost: Credits per generation
            - max_reference_images: Maximum reference images allowed
            - max_images_per_request: Maximum images per request
            - supported_resolutions: List of supported resolutions
            - supported_aspect_ratios: List of supported aspect ratios
        """
        return self.get("models")

    def get_models_async(
        self,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """Get list of available models asynchronously."""
        return self.get_async(
            "models",
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    def get_styles(self) -> APIResponse:
        """
        Get list of available style presets.

        Returns:
            APIResponse with data.styles list containing:
            - name: Style identifier (e.g., "photorealistic", "artistic")
            - display_name: UI display name (e.g., "Photorealistic")
            - description: Style description
        """
        return self.get("styles")

    def get_styles_async(
        self,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """Get list of available styles asynchronously."""
        return self.get_async(
            "styles",
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    # ========================================================================
    # GENERATION METHODS
    # ========================================================================

    def generate(
        self,
        prompt: str,
        model: str = "flash",
        style: str = "none",
        aspect_ratio: str = "1:1",
        resolution: str = "1K",
        number_of_images: int = 1,
        negative_prompt: Optional[str] = None,
        reference_images: Optional[List[bytes]] = None,
    ) -> APIResponse:
        """
        Generate images using AI.

        Args:
            prompt: Text description of desired image
            model: Model to use (e.g., "flash", "pro")
            style: Style preset (e.g., "photorealistic", "none")
            aspect_ratio: Output aspect ratio (e.g., "1:1", "16:9")
            resolution: Output resolution (e.g., "1K", "2K", "4K")
            number_of_images: Number of images to generate (1-4)
            negative_prompt: What to avoid in generation
            reference_images: List of reference image bytes

        Returns:
            APIResponse with images list, remaining_credits, etc.
        """
        import json

        _require_auth()

        # Build parameters JSON
        parameters = {
            "style": style,
            "aspect_ratio": aspect_ratio,
            "number_of_images": number_of_images,
        }

        # Only include resolution for pro model
        if model == "pro" and resolution:
            parameters["resolution"] = resolution

        if negative_prompt:
            parameters["negative_prompt"] = negative_prompt

        # Build multipart form data according to API spec
        files = [
            ("prompt", (None, prompt)),
            ("model_name", (None, model)),
            ("parameters_json", (None, json.dumps(parameters))),
        ]

        if reference_images:
            for i, img_bytes in enumerate(reference_images):
                files.append(("reference_images", (f"ref_{i}.jpg", img_bytes, "image/jpeg")))

        return self.post("generate", files=files)

    def generate_async(
        self,
        prompt: str,
        model: str = "flash",
        style: str = "none",
        aspect_ratio: str = "1:1",
        resolution: str = "1K",
        number_of_images: int = 1,
        negative_prompt: Optional[str] = None,
        reference_images: Optional[List[bytes]] = None,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Generate images using AI asynchronously.

        Args:
            prompt: Text description of desired image
            model: Model to use (e.g., "flash", "pro")
            style: Style preset (e.g., "photorealistic", "none")
            aspect_ratio: Output aspect ratio (e.g., "1:1", "16:9")
            resolution: Output resolution (e.g., "1K", "2K", "4K")
            number_of_images: Number of images to generate (1-4)
            negative_prompt: What to avoid in generation
            reference_images: List of reference image bytes
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking
        """
        import json

        _require_auth()

        # Build parameters JSON
        parameters = {
            "style": style,
            "aspect_ratio": aspect_ratio,
            "number_of_images": number_of_images,
        }

        # Only include resolution for pro model
        if model == "pro" and resolution:
            parameters["resolution"] = resolution

        if negative_prompt:
            parameters["negative_prompt"] = negative_prompt

        # Build multipart form data according to API spec
        files = [
            ("prompt", (None, prompt)),
            ("model_name", (None, model)),
            ("parameters_json", (None, json.dumps(parameters))),
        ]

        if reference_images:
            for i, img_bytes in enumerate(reference_images):
                files.append(("reference_images", (f"ref_{i}.jpg", img_bytes, "image/jpeg")))

        return self.post_async(
            "generate",
            files=files,
            timeout=IMAGEGEN_TIMEOUT,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )


# Singleton instance
_imagegen_service: Optional[ImageGenService] = None


def get_imagegen_service() -> ImageGenService:
    """Get the global ImageGenService instance."""
    global _imagegen_service
    if _imagegen_service is None:
        _imagegen_service = ImageGenService()
    return _imagegen_service
