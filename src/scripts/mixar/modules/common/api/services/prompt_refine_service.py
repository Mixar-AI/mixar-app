# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Prompt refinement — ``POST /api/v1/prompt-refine/refine``.

One short call that rewrites a generation prompt for the model it is about to
be sent to. It is NOT a queue job: the result is text that goes straight back
into the field the user is looking at, so it returns inline and never appears
in the Queue list.

Async only. The user is watching the prompt box, but they are also free to
keep working, and the shared request queue already delivers its callbacks on
Blender's main thread.
"""

from typing import Callable, Optional

from ..constants import APIModule
from ..response import APIResponse
from .base_service import BaseService


class PromptRefineService(BaseService):
    """Client for the prompt refinement endpoint."""

    @property
    def module(self) -> APIModule:
        return APIModule.PROMPT_REFINE

    def refine_async(
        self,
        prompt: str,
        *,
        service_key: str = "",
        model_slug: str = "",
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        timeout: float = 45.0,
    ) -> str:
        """Refine *prompt* for a generation target.

        ``service_key``/``model_slug`` name the GENERATION target (the
        service key and the selected model slug), never the refiner — the
        backend keys its instructions on that pair, because what improves an
        image prompt is not what improves a video prompt. Both may be empty:
        the backend then refines through its default profile.

        The client timeout sits above the backend's own refinement timeout so
        a slow-but-completing call is answered rather than abandoned twice.
        """
        return self.post_async(
            "refine",
            json={
                "prompt": prompt,
                "service_key": service_key or "",
                "model_slug": model_slug or "",
            },
            timeout=timeout,
            on_success=on_success,
            on_error=on_error,
        )


_instance: Optional[PromptRefineService] = None


def get_prompt_refine_service() -> PromptRefineService:
    """Cached singleton."""
    global _instance
    if _instance is None:
        _instance = PromptRefineService()
    return _instance
