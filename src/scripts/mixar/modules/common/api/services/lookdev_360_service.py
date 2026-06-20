# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Lookdev 360 API Service.

Handles /api/v1/pbr-generation/mesh-to-pbr endpoint for PBR texture generation from meshes.
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


class Lookdev360Service(BaseService):
    """
    Lookdev 360 service for generating PBR textures from OBJ mesh files.

    Uses the PBR Generation API's mesh-to-pbr endpoint.

    Endpoints:
    - POST /mesh-to-pbr - Generate PBR textures (BaseColor, MR) from OBJ file
    """

    @property
    def module(self) -> APIModule:
        return APIModule.PBR_GENERATION

    # ========================================================================
    # SYNC METHODS
    # ========================================================================

    def generate(
        self,
        mesh_file: Union[BinaryIO, bytes, str],
        prompt: str,
        mesh_filename: str = "model.obj",
        model_name: str = "hunyuan-pbr",
        style_ref_image: Optional[Union[bytes, str]] = None,
        reference_image: Optional[Union[bytes, str]] = None,
        resolution: Optional[int] = None,
        negative_prompt: Optional[str] = None,
    ) -> APIResponse:
        """
        Generate PBR textures from an OBJ mesh file.

        Args:
            mesh_file: OBJ file (file object, bytes, or file path) - required
            prompt: Text description of desired texture appearance - required
            mesh_filename: Filename for the mesh file (used in multipart)
            model_name: Model to use (default: hunyuan-pbr)
            style_ref_image: Style reference image as bytes or file path (mutually exclusive with reference_image)
            reference_image: Reference image as bytes or file path - directly drives generation (mutually exclusive with style_ref_image)
            resolution: Output texture resolution (512, 1024, 2048, default: 1024)
            negative_prompt: What to avoid in generation

        Returns:
            APIResponse with generated PBR texture data (BaseColor, MR)

        Raises:
            AuthenticationError: If no access token is available
        """
        _require_auth()

        # Handle different mesh_file input types
        if isinstance(mesh_file, str):
            # It's a file path
            with open(mesh_file, "rb") as f:
                file_content = f.read()
            files = {"mesh_file": (mesh_filename, file_content)}
        elif isinstance(mesh_file, bytes):
            files = {"mesh_file": (mesh_filename, mesh_file)}
        else:
            # Assume it's a file-like object
            files = {"mesh_file": (mesh_filename, mesh_file)}

        # Handle style_ref_image as file upload if provided
        if style_ref_image is not None:
            if isinstance(style_ref_image, bytes):
                files["style_ref_image"] = ("style_ref_image.png", style_ref_image)
            elif isinstance(style_ref_image, str):
                # It's a file path - read it
                with open(style_ref_image, "rb") as f:
                    files["style_ref_image"] = ("style_ref_image.png", f.read())

        # Handle reference_image as file upload if provided
        if reference_image is not None:
            if isinstance(reference_image, bytes):
                files["reference_image"] = ("reference_image.png", reference_image)
            elif isinstance(reference_image, str):
                with open(reference_image, "rb") as f:
                    files["reference_image"] = ("reference_image.png", f.read())

        # Build form data
        data: Dict[str, Any] = {
            "prompt": prompt,
            "model_name": model_name,
        }

        # Build parameters JSON if any optional params provided
        params: Dict[str, Any] = {}
        if resolution is not None:
            params["resolution"] = resolution
        if negative_prompt is not None:
            params["negative_prompt"] = negative_prompt

        if params:
            data["parameters_json"] = json.dumps(params)

        return self.post("mesh-to-pbr", files=files, data=data)

    # ========================================================================
    # ASYNC METHODS
    # ========================================================================

    def generate_async(
        self,
        mesh_file: Union[BinaryIO, bytes, str],
        prompt: str,
        mesh_filename: str = "model.obj",
        model_name: str = "hunyuan-pbr",
        style_ref_image: Optional[Union[bytes, str]] = None,
        reference_image: Optional[Union[bytes, str]] = None,
        resolution: Optional[int] = None,
        negative_prompt: Optional[str] = None,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Generate PBR textures from an OBJ mesh file asynchronously.

        Args:
            mesh_file: OBJ file (file object, bytes, or file path) - required
            prompt: Text description of desired texture appearance - required
            mesh_filename: Filename for the mesh file
            model_name: Model to use (default: hunyuan-pbr)
            style_ref_image: Style reference image as bytes or file path (mutually exclusive with reference_image)
            reference_image: Reference image as bytes or file path - directly drives generation (mutually exclusive with style_ref_image)
            resolution: Output texture resolution (512, 1024, 2048, default: 1024)
            negative_prompt: What to avoid in generation
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking

        Raises:
            AuthenticationError: If no access token is available
        """
        _require_auth()

        # Handle different mesh_file input types
        # For async, we need to read the file content on the main thread
        if isinstance(mesh_file, str):
            # It's a file path - read it now
            with open(mesh_file, "rb") as f:
                file_content = f.read()
            files = {"mesh_file": (mesh_filename, file_content)}
        elif isinstance(mesh_file, bytes):
            files = {"mesh_file": (mesh_filename, mesh_file)}
        else:
            # Assume it's a file-like object - read it now for thread safety
            file_content = mesh_file.read()
            files = {"mesh_file": (mesh_filename, file_content)}

        # Handle style_ref_image as file upload if provided
        if style_ref_image is not None:
            if isinstance(style_ref_image, bytes):
                files["style_ref_image"] = ("style_ref_image.png", style_ref_image)
            elif isinstance(style_ref_image, str):
                # It's a file path - read it
                with open(style_ref_image, "rb") as f:
                    files["style_ref_image"] = ("style_ref_image.png", f.read())

        # Handle reference_image as file upload if provided
        if reference_image is not None:
            if isinstance(reference_image, bytes):
                files["reference_image"] = ("reference_image.png", reference_image)
            elif isinstance(reference_image, str):
                with open(reference_image, "rb") as f:
                    files["reference_image"] = ("reference_image.png", f.read())

        # Build form data
        data: Dict[str, Any] = {
            "prompt": prompt,
            "model_name": model_name,
        }

        # Build parameters JSON if any optional params provided
        params: Dict[str, Any] = {}
        if resolution is not None:
            params["resolution"] = resolution
        if negative_prompt is not None:
            params["negative_prompt"] = negative_prompt

        if params:
            data["parameters_json"] = json.dumps(params)

        # Use longer timeout for PBR generation (can take 60+ seconds)
        return self.post_async(
            "mesh-to-pbr",
            files=files,
            data=data,
            timeout=1200.0,  # 20 minutes for long-running generation
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )


# Singleton instance
_lookdev_360_service: Optional[Lookdev360Service] = None


def get_lookdev_360_service() -> Lookdev360Service:
    """Get the global Lookdev360Service instance."""
    global _lookdev_360_service
    if _lookdev_360_service is None:
        _lookdev_360_service = Lookdev360Service()
    return _lookdev_360_service
