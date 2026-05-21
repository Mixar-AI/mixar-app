# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Images API Service.

Handles /api/v1/images endpoints for image/asset management.
"""

from typing import Any, BinaryIO, Callable, Dict, List, Optional

from ..constants import APIModule
from ..request_queue import AsyncResponse
from ..response import APIResponse
from .base_service import BaseService


class ImagesService(BaseService):
    """
    Images service for asset management.

    Endpoints:
    - POST /upload - Upload an image
    - GET /{id} - Get image by ID
    - DELETE /{id} - Delete image
    - POST /generate - Generate image with AI
    """

    @property
    def module(self) -> APIModule:
        return APIModule.IMAGES

    # ========================================================================
    # SYNC METHODS
    # ========================================================================

    def upload(
        self,
        file: BinaryIO,
        filename: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """
        Upload an image file.

        Args:
            file: File object to upload
            filename: Original filename
            metadata: Optional metadata

        Returns:
            APIResponse with uploaded image info
        """
        files = {"file": (filename, file)}
        data = {"metadata": metadata} if metadata else None
        return self.post("upload", files=files, data=data)

    def get_image(self, image_id: str) -> APIResponse:
        """
        Get image info by ID.

        Args:
            image_id: Image identifier

        Returns:
            APIResponse with image data
        """
        return self.get(image_id)

    def delete_image(self, image_id: str) -> APIResponse:
        """
        Delete an image.

        Args:
            image_id: Image identifier

        Returns:
            APIResponse confirming deletion
        """
        return self.delete(image_id)

    def generate(
        self,
        prompt: str,
        model: str = "gemini-2.5-flash-image",
        aspect_ratio: str = "16:9",
        reference_images: Optional[List[str]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """
        Generate an image using AI.

        Args:
            prompt: Generation prompt
            model: Model to use
            aspect_ratio: Output aspect ratio
            reference_images: List of reference image IDs
            options: Additional generation options

        Returns:
            APIResponse with generated image
        """
        payload = {
            "prompt": prompt,
            "model": model,
            "aspect_ratio": aspect_ratio,
        }
        if reference_images:
            payload["reference_images"] = reference_images
        if options:
            payload["options"] = options

        return self.post("generate", json=payload)

    # ========================================================================
    # ASYNC METHODS
    # ========================================================================

    def get_image_async(
        self,
        image_id: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Get image info by ID asynchronously.

        Args:
            image_id: Image identifier
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking
        """
        return self.get_async(
            image_id,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    def delete_image_async(
        self,
        image_id: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Delete an image asynchronously.

        Args:
            image_id: Image identifier
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking
        """
        return self.delete_async(
            image_id,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    def generate_async(
        self,
        prompt: str,
        model: str = "gemini-2.5-flash-image",
        aspect_ratio: str = "16:9",
        reference_images: Optional[List[str]] = None,
        options: Optional[Dict[str, Any]] = None,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Generate an image using AI asynchronously.

        Args:
            prompt: Generation prompt
            model: Model to use
            aspect_ratio: Output aspect ratio
            reference_images: List of reference image IDs
            options: Additional generation options
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking
        """
        payload = {
            "prompt": prompt,
            "model": model,
            "aspect_ratio": aspect_ratio,
        }
        if reference_images:
            payload["reference_images"] = reference_images
        if options:
            payload["options"] = options

        return self.post_async(
            "generate",
            json=payload,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )


# Singleton instance
_images_service: Optional[ImagesService] = None


def get_images_service() -> ImagesService:
    """Get the global ImagesService instance."""
    global _images_service
    if _images_service is None:
        _images_service = ImagesService()
    return _images_service
