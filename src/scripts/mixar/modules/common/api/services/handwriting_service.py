# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Handwriting API service.

Backs Mixar Scribble: the chat ink overlay rasterizes the strokes the user
wrote with a stylus and posts the image here, and the recognized text is
appended to the chat composer.
"""

from typing import Callable, Optional

from ..constants import APIModule
from ..request_queue import AsyncResponse
from ..response import APIResponse
from .base_service import BaseService


class HandwritingService(BaseService):
    """
    Handwriting service.

    Endpoints (/api/v1/handwriting/):
    - POST /recognize - Transcribe an image of handwriting to text
    """

    @property
    def module(self) -> APIModule:
        """Return the HANDWRITING module."""
        return APIModule.HANDWRITING

    # ========================================================================
    # RECOGNIZE
    # ========================================================================

    def recognize(
        self,
        image_bytes: bytes,
        filename: str = "scribble.png",
        hint: str = "",
        timeout: float = 60.0,
    ) -> APIResponse:
        """
        Transcribe an image of handwriting.

        Args:
            image_bytes: Rasterized ink — dark strokes on a light background
            filename: Filename for the upload
            hint: Optional tail of the text already in the composer, sent as
                a form field so a continued sentence is read in context

        Returns:
            APIResponse whose data envelope contains:
            - text: str — the transcription. Empty when nothing legible was
              written; that is a normal result, not an error.
            - confidence: float 0..1
        """
        files = {"image": (filename, image_bytes, _mime_type(filename))}
        return self._client.post(
            self._endpoint("recognize"),
            files=files,
            data=_hint_data(hint),
            timeout=timeout,
        )

    def recognize_async(
        self,
        image_bytes: bytes,
        filename: str = "scribble.png",
        hint: str = "",
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
        timeout: float = 60.0,
    ) -> str:
        """
        Transcribe an image of handwriting asynchronously.

        The request runs on a background thread; callbacks are delivered on
        Blender's main thread by the shared request queue.

        Returns:
            Request ID for tracking
        """
        files = {"image": (filename, image_bytes, _mime_type(filename))}
        return self._client.request_async(
            "POST",
            self._endpoint("recognize"),
            files=files,
            data=_hint_data(hint),
            timeout=timeout,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )


def _hint_data(hint: str) -> Optional[dict]:
    """Multipart form fields for an optional recognition hint.

    Omitted entirely when blank — the field is optional backend-side and an
    empty composer is no context at all.
    """
    hint = (hint or "").strip()
    return {"hint": hint} if hint else None


def _mime_type(filename: str) -> str:
    """Determine MIME type from filename."""
    lower = filename.lower()
    if lower.endswith(('.jpg', '.jpeg')):
        return "image/jpeg"
    if lower.endswith('.webp'):
        return "image/webp"
    return "image/png"


# Singleton instance
_handwriting_service: Optional[HandwritingService] = None


def get_handwriting_service() -> HandwritingService:
    """Get or create the global Handwriting service instance."""
    global _handwriting_service
    if _handwriting_service is None:
        _handwriting_service = HandwritingService()
    return _handwriting_service
