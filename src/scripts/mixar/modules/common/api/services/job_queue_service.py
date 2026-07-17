# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unified Job Queue API Service.

Handles communication with the backend unified job queue:
- POST   /job-queue/jobs:       Submit a new job
- GET    /job-queue/jobs/{id}:  Get job status/result
- GET    /job-queue/jobs:       List user's jobs
- DELETE /job-queue/jobs/{id}:  Cancel a job

Responses are normalized to the Blender-side status names used by
existing concrete Job classes.
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


_STATE_TO_STATUS = {
    "pending": "PENDING",
    "dispatched": "SUBMITTED",
    "running": "POLLING",
    "succeeded": "DONE",
    "failed": "FAILED",
    "dlq": "DLQ",
    "cancelled": "CANCELLED",
}


def _require_auth() -> None:
    token = get_access_token()
    if not token:
        raise AuthenticationError(
            message="Authentication required. Please login first.",
            status_code=401,
        )


class JobQueueService(BaseService):
    """API client for the backend unified job queue."""

    @property
    def module(self) -> APIModule:
        return APIModule.JOB_QUEUE

    @staticmethod
    def _normalize_response(response: APIResponse) -> APIResponse:
        """Adapt /job-queue response data to the job queue response envelope."""
        outer = response.data if isinstance(response.data, dict) else {}
        data = outer.get("data", outer) if isinstance(outer, dict) else {}
        if not isinstance(data, dict):
            return response

        state = str(data.get("state") or data.get("status") or "").lower()
        status = _STATE_TO_STATUS.get(state, data.get("status") or "")
        error = data.get("error")
        user_message = ""
        if status == "CANCELLED":
            user_message = "Generation was cancelled"
            error = error or "Cancelled"
        elif status == "FAILED":
            user_message = "Generation failed — please try again"

        normalized = {
            "job_id": data.get("job_id") or data.get("id"),
            "status": status,
            "queue_position": data.get("queue_position"),
            "result": data.get("result"),
            "error": error,
            "user_message": data.get("user_message") or user_message,
            "version": data.get("version"),
            "attempts": data.get("attempts"),
            "service": data.get("service"),
        }
        # Preserve omission for rolling deploys: older backends do not send
        # model, and a missing key must not erase the locally submitted value.
        if "model" in data:
            normalized["model"] = data.get("model")
        return APIResponse(
            success=response.success,
            status_code=response.status_code,
            data={
                "status": outer.get("status", "success"),
                "message": outer.get("message", response.message),
                "data": normalized,
            },
            message=response.message,
            headers=response.headers,
            raw=response.raw,
        )

    @classmethod
    def _wrap_success(cls, callback):
        if callback is None:
            return None

        def _wrapped(response):
            callback(cls._normalize_response(response))

        return _wrapped

    def enqueue(
        self,
        job_type: str,
        model: str,
        payload: dict,
        idempotency_key: Optional[str] = None,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
        timeout: float = 120.0,
    ) -> str:
        """POST /job-queue/jobs

        Args:
            timeout: Request timeout in seconds.
        """
        _require_auth()
        idempotency_key = idempotency_key or str(uuid.uuid4())
        return self.post_async(
            "jobs",
            json={
                "service": job_type,
                "model": model,
                "payload": payload,
                "idempotency_key": idempotency_key,
            },
            on_success=self._wrap_success(on_success),
            on_error=on_error,
            on_complete=on_complete,
            timeout=timeout,
        )

    def get_job_status(
        self,
        job_id: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """GET /job-queue/jobs/{job_id} (async)"""
        _require_auth()
        return self.get_async(
            f"jobs/{job_id}",
            on_success=self._wrap_success(on_success),
            on_error=on_error,
            on_complete=on_complete,
        )

    def get_job_status_sync(self, job_id: str) -> "APIResponse":
        """GET /job-queue/jobs/{job_id} (synchronous).

        Safe to call from background threads — used by managers that
        poll from their own daemon threads.
        """
        _require_auth()
        return self._normalize_response(self.get(f"jobs/{job_id}"))

    def cancel_job(
        self,
        job_id: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> str:
        """DELETE /job-queue/jobs/{job_id}"""
        _require_auth()
        return self.delete_async(
            f"jobs/{job_id}",
            on_success=self._wrap_success(on_success),
            on_error=on_error,
        )

    def get_queue_info(
        self,
        job_type: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> str:
        """GET /job-queue/info/{job_type}"""
        _require_auth()
        return self.get_async(
            f"info/{job_type}",
            on_success=on_success,
            on_error=on_error,
        )


# Singleton
_service: Optional[JobQueueService] = None


def get_job_queue_service() -> JobQueueService:
    global _service
    if _service is None:
        _service = JobQueueService()
    return _service
