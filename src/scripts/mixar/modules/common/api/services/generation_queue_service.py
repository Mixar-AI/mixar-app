# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generation Queue API Service.

Handles communication with the backend generation queue:
- POST /generation-queue/enqueue:     Enqueue a new job
- GET  /generation-queue/jobs/{id}:   Get job status
- GET  /generation-queue/jobs:        List user's jobs
- DELETE /generation-queue/jobs/{id}: Cancel a PENDING job
- GET  /generation-queue/info/{type}: Queue info
"""

import uuid
from typing import Callable, Optional

from mixar.config.logging_config import get_logger

from ....auth.core.auth import get_access_token
from ..constants import APIModule
from ..exceptions import AuthenticationError
from ..request_queue import AsyncResponse
from ..response import APIResponse
from .base_service import BaseService

logger = get_logger(__name__)


def _require_auth() -> None:
    token = get_access_token()
    if not token:
        raise AuthenticationError(
            message="Authentication required. Please login first.",
            status_code=401,
        )


class GenerationQueueService(BaseService):
    """API client for the backend generation queue."""

    @property
    def module(self) -> APIModule:
        return APIModule.GENERATION_QUEUE

    def enqueue(
        self,
        job_type: str,
        model: str,
        payload: dict,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """POST /generation-queue/enqueue"""
        _require_auth()
        idempotency_key = str(uuid.uuid4())
        return self.post_async(
            "enqueue",
            json={
                "job_type": job_type,
                "model": model,
                "payload": payload,
                "idempotency_key": idempotency_key,
            },
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
            timeout=120.0,  # Large payloads (base64 GLB files) need longer timeout
        )

    def get_job_status(
        self,
        job_id: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """GET /generation-queue/jobs/{job_id}"""
        _require_auth()
        return self.get_async(
            f"jobs/{job_id}",
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    def cancel_job(
        self,
        job_id: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> str:
        """DELETE /generation-queue/jobs/{job_id}"""
        _require_auth()
        return self.delete_async(
            f"jobs/{job_id}",
            on_success=on_success,
            on_error=on_error,
        )

    def get_queue_info(
        self,
        job_type: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> str:
        """GET /generation-queue/info/{job_type}"""
        _require_auth()
        return self.get_async(
            f"info/{job_type}",
            on_success=on_success,
            on_error=on_error,
        )


# Singleton
_service: Optional[GenerationQueueService] = None


def get_generation_queue_service() -> GenerationQueueService:
    global _service
    if _service is None:
        _service = GenerationQueueService()
    return _service
