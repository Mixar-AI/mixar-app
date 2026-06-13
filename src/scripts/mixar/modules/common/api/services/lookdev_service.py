# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Lookdev API Service.

Handles /api/v1/image-generation/generate-from-depth endpoint for depth-to-image generation.
"""

import json
from typing import Any, BinaryIO, Callable, Dict, Optional, Union

from ....auth.core.auth import get_access_token
from ..constants import APIModule
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


class LookdevService(BaseService):
    """
    Lookdev service for generating images using depth maps.

    Uses the Image Generation API's generate-from-depth endpoint.

    Endpoints:
    - POST /generate-from-depth - Generate image using depth map and prompt
    """

    @property
    def module(self) -> APIModule:
        return APIModule.IMAGEGEN

    # ========================================================================
    # SYNC METHODS
    # ========================================================================

    def generate(
        self,
        depth_map: Union[BinaryIO, bytes, str],
        prompt: str,
        depth_map_filename: str = "depth_map.png",
        model_name: str = "flux-depth-dev",
        guidance: Optional[float] = None,
        num_outputs: Optional[int] = None,
        num_inference_steps: Optional[int] = None,
        megapixels: Optional[str] = None,
        output_format: Optional[str] = None,
        output_quality: Optional[int] = None,
        seed: Optional[int] = None,
    ) -> APIResponse:
        """
        Generate an image using a depth map and prompt.

        Args:
            depth_map: Depth map image file (file object, bytes, or file path)
            prompt: Text prompt for generation
            depth_map_filename: Filename for the depth map (used in multipart)
            model_name: Model to use (default: flux-depth-dev)
            guidance: Guidance scale (0-100, default: 10)
            num_outputs: Number of images to generate (1-4, default: 1)
            num_inference_steps: Denoising steps (1-50, default: 28)
            megapixels: Output resolution ("1", "0.25", "match_input", default: "1")
            output_format: Output format ("webp", "jpg", "png", default: "webp")
            output_quality: Output quality (0-100, default: 80)
            seed: Random seed for reproducibility

        Returns:
            APIResponse with generated image data

        Raises:
            AuthenticationError: If no access token is available
        """
        _require_auth()

        # Handle different depth_map input types
        if isinstance(depth_map, str):
            # It's a file path
            with open(depth_map, "rb") as f:
                file_content = f.read()
            files = {"depth_map": (depth_map_filename, file_content)}
        elif isinstance(depth_map, bytes):
            files = {"depth_map": (depth_map_filename, depth_map)}
        else:
            # Assume it's a file-like object
            files = {"depth_map": (depth_map_filename, depth_map)}

        # Build form data
        data: Dict[str, Any] = {
            "prompt": prompt,
            "model_name": model_name,
        }

        # Build parameters JSON if any optional params provided
        params: Dict[str, Any] = {}
        if guidance is not None:
            params["guidance"] = guidance
        if num_outputs is not None:
            params["num_outputs"] = num_outputs
        if num_inference_steps is not None:
            params["num_inference_steps"] = num_inference_steps
        if megapixels is not None:
            params["megapixels"] = megapixels
        if output_format is not None:
            params["output_format"] = output_format
        if output_quality is not None:
            params["output_quality"] = output_quality
        if seed is not None:
            params["seed"] = seed

        if params:
            data["parameters_json"] = json.dumps(params)

        return self.post("generate-from-depth", files=files, data=data)

    # ========================================================================
    # ASYNC METHODS
    # ========================================================================

    def generate_async(
        self,
        depth_map: Union[BinaryIO, bytes, str],
        prompt: str,
        depth_map_filename: str = "depth_map.png",
        model_name: str = "flux-depth-dev",
        guidance: Optional[float] = None,
        num_outputs: Optional[int] = None,
        num_inference_steps: Optional[int] = None,
        megapixels: Optional[str] = None,
        output_format: Optional[str] = None,
        output_quality: Optional[int] = None,
        seed: Optional[int] = None,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Generate an image using a depth map and prompt asynchronously.

        Args:
            depth_map: Depth map image file (file object, bytes, or file path)
            prompt: Text prompt for generation
            depth_map_filename: Filename for the depth map
            model_name: Model to use (default: flux-depth-dev)
            guidance: Guidance scale (0-100, default: 10)
            num_outputs: Number of images to generate (1-4, default: 1)
            num_inference_steps: Denoising steps (1-50, default: 28)
            megapixels: Output resolution ("1", "0.25", "match_input", default: "1")
            output_format: Output format ("webp", "jpg", "png", default: "webp")
            output_quality: Output quality (0-100, default: 80)
            seed: Random seed for reproducibility
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking

        Raises:
            AuthenticationError: If no access token is available
        """
        _require_auth()

        # Handle different depth_map input types
        # For async, we need to read the file content on the main thread
        if isinstance(depth_map, str):
            # It's a file path - read it now
            with open(depth_map, "rb") as f:
                file_content = f.read()
            files = {"depth_map": (depth_map_filename, file_content)}
        elif isinstance(depth_map, bytes):
            files = {"depth_map": (depth_map_filename, depth_map)}
        else:
            # Assume it's a file-like object - read it now for thread safety
            file_content = depth_map.read()
            files = {"depth_map": (depth_map_filename, file_content)}

        # Build form data
        data: Dict[str, Any] = {
            "prompt": prompt,
            "model_name": model_name,
        }

        # Build parameters JSON if any optional params provided
        params: Dict[str, Any] = {}
        if guidance is not None:
            params["guidance"] = guidance
        if num_outputs is not None:
            params["num_outputs"] = num_outputs
        if num_inference_steps is not None:
            params["num_inference_steps"] = num_inference_steps
        if megapixels is not None:
            params["megapixels"] = megapixels
        if output_format is not None:
            params["output_format"] = output_format
        if output_quality is not None:
            params["output_quality"] = output_quality
        if seed is not None:
            params["seed"] = seed

        if params:
            data["parameters_json"] = json.dumps(params)

        return self.post_async(
            "generate-from-depth",
            files=files,
            data=data,
            timeout=120.0,  # 2 minutes for long-running generation
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )


# Singleton instance
_lookdev_service: Optional[LookdevService] = None


def get_lookdev_service() -> LookdevService:
    """Get the global LookdevService instance."""
    global _lookdev_service
    if _lookdev_service is None:
        _lookdev_service = LookdevService()
    return _lookdev_service
