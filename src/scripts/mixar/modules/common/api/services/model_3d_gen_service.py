# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Model 3D Gen API Service.

Handles dynamic 3D model generation using the unified API.
Endpoints:
- GET /models: List available models
- GET /models/{model_name}: Get model details and parameters
- POST /generate: Unified generation endpoint
"""

import json
from typing import BinaryIO, Callable, Dict, Optional, Union

from ....auth.core.auth import get_access_token
from ..constants import APIModule
from ..exceptions import AuthenticationError
from ..request_queue import AsyncResponse
from ..response import APIResponse
from .base_service import BaseService

# Generation typically takes 5-10 minutes
GENERATION_TIMEOUT = 600.0  # 10 minutes


def _require_auth() -> None:
    """Raise AuthenticationError if no access token is available."""
    token = get_access_token()
    if not token:
        raise AuthenticationError(
            message="Authentication required. Please login first.",
            status_code=401,
        )


class Model3DGenService(BaseService):
    """
    Model 3D generation service using the unified API.

    Provides:
    - Dynamic model listing
    - Unified generation endpoint
    - Model-agnostic parameter handling
    """

    @property
    def module(self) -> APIModule:
        return APIModule.MODEL_3D_GEN

    # ========================================================================
    # MODEL LISTING METHODS
    # ========================================================================

    def get_models(self) -> APIResponse:
        """
        Get list of available 3D generation models.

        Returns:
            APIResponse with data.models list containing:
            - name: Model identifier (e.g., "trellis-1", "rodin")
            - display_name: UI display name (e.g., "Trellis 1.0")
            - credit_cost: Credits required per generation
        """
        return self.get("models")

    def get_models_async(
        self,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """Get list of available 3D generation models asynchronously."""
        return self.get_async(
            "models",
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    def get_model_details(self, model_name: str) -> APIResponse:
        """
        Get detailed information about a specific model.

        Args:
            model_name: Model identifier (e.g., "trellis-1")

        Returns:
            APIResponse with model details including parameters schema
        """
        return self.get(f"models/{model_name}")

    def get_model_details_async(
        self,
        model_name: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """Get detailed information about a specific model asynchronously."""
        return self.get_async(
            f"models/{model_name}",
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    # ========================================================================
    # GENERATION METHODS
    # ========================================================================

    def generate(
        self,
        image: Union[BinaryIO, bytes, str],
        model_name: str,
        prompt: Optional[str] = None,
        parameters: Optional[Dict] = None,
        image_filename: str = "image.png",
    ) -> APIResponse:
        """
        Generate a 3D model from an image using the specified model.

        Args:
            image: Input image (file object, bytes, or file path)
            model_name: Model to use (e.g., "trellis-1", "rodin")
            prompt: Optional text prompt for context
            parameters: Optional dict of model-specific parameters
            image_filename: Filename for multipart upload

        Returns:
            APIResponse with model_url, remaining_credits, etc.
        """
        _require_auth()

        files = self._prepare_image_files(image, image_filename)
        data = {"model_name": model_name}

        if prompt:
            data["prompt"] = prompt

        if parameters:
            data["parameters_json"] = json.dumps(parameters)

        return self.post("generate", files=files, data=data)

    def generate_async(
        self,
        image: Union[BinaryIO, bytes, str],
        model_name: str,
        prompt: Optional[str] = None,
        parameters: Optional[Dict] = None,
        image_filename: str = "image.png",
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Generate a 3D model from an image asynchronously.

        Args:
            image: Input image (file object, bytes, or file path)
            model_name: Model to use (e.g., "trellis-1", "rodin")
            prompt: Optional text prompt for context
            parameters: Optional dict of model-specific parameters
            image_filename: Filename for multipart upload
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking
        """
        _require_auth()

        files = self._prepare_image_files(image, image_filename)
        data = {"model_name": model_name}

        if prompt:
            data["prompt"] = prompt

        if parameters:
            data["parameters_json"] = json.dumps(parameters)

        return self.post_async(
            "generate",
            files=files,
            data=data,
            timeout=GENERATION_TIMEOUT,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    def _prepare_image_files(
        self,
        image: Union[BinaryIO, bytes, str],
        image_filename: str,
    ) -> dict:
        """Prepare image files dict for multipart upload."""
        mime_type = "image/png"
        lower_name = image_filename.lower()
        if lower_name.endswith((".jpg", ".jpeg")):
            mime_type = "image/jpeg"
        elif lower_name.endswith(".webp"):
            mime_type = "image/webp"

        if isinstance(image, str):
            with open(image, "rb") as f:
                file_content = f.read()
            return {"image": (image_filename, file_content, mime_type)}
        elif isinstance(image, bytes):
            return {"image": (image_filename, image, mime_type)}
        else:
            file_content = image.read()
            return {"image": (image_filename, file_content, mime_type)}


# Singleton instance
_model_3d_gen_service: Optional[Model3DGenService] = None


def get_model_3d_gen_service() -> Model3DGenService:
    """Get the global Model3DGenService instance."""
    global _model_3d_gen_service
    if _model_3d_gen_service is None:
        _model_3d_gen_service = Model3DGenService()
    return _model_3d_gen_service
