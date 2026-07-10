# SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Backend-service bridge: generation jobs, catalog, and BYOK key providers.

These endpoints reuse Mixar's existing client services so an MCP client gets
the exact same GPU-generation and bring-your-own-key surface the in-app UI
has. Everything here talks to whatever `backend_url` the app is configured
with, using the user's own Mixar session — the MCP layer adds zero hosted
agent-token usage on top.

All service calls are synchronous HTTP and safe from the bridge's daemon
thread (same pattern as JobQueueService.get_job_status_sync).
"""

import re
from typing import Any, Optional

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Field names whose values must never surface in responses or logs. Redacted
# defensively even though the backend contract is that keys are write-only —
# an error path or a chatty backend must not leak a provider key into the LLM
# conversation or Mixar's log file.
_SECRET_KEYS = ("api_key", "apikey", "key", "secret", "token", "password")


def _redact(value: Any) -> Any:
    """Recursively drop secret-shaped fields from a JSON-ish structure."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in _SECRET_KEYS:
                out[k] = "***redacted***"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _redact_text(text: str) -> str:
    """Blank out anything that looks like `key=...`/`key: ...` in error text."""
    pattern = r"(?i)\b(api[_-]?key|secret|token|password)\b\s*[=:]\s*\S+"
    return re.sub(pattern, r"\1=***redacted***", text)


def _api_result(response) -> dict:
    """Normalize an APIResponse into the bridge's envelope (secrets redacted)."""
    data = _redact(getattr(response, "data", None))
    return {
        "success": bool(getattr(response, "success", False)),
        "status_code": getattr(response, "status_code", None),
        "data": data,
        "message": getattr(response, "message", "") or "",
    }


def _guarded(fn) -> dict:
    """Run a service call, translating auth/network errors into envelopes."""
    try:
        return fn()
    except Exception as exc:
        name = type(exc).__name__
        hint = ""
        if "Authentication" in name or getattr(exc, "status_code", None) == 401:
            hint = " Login to Mixar in the app first (backend features use your Mixar session)."
        safe = _redact_text("{0}".format(exc))
        logger.warning("MCP bridge service call failed: %s: %s", name, safe)
        return {"success": False, "error": "{0}: {1}{2}".format(name, safe, hint)}


# ── Generation: unified job queue ────────────────────────────────────────────

def generation_enqueue(service: str, model: str, payload: dict) -> dict:
    """Submit a job to the unified queue (POST /job-queue/jobs)."""
    if not service or not model:
        return {"success": False, "error": "'service' and 'model' are required"}

    def _call() -> dict:
        import uuid

        from mixar.modules.common.api.services import job_queue_service as jq

        # Match the auth pre-check the public enqueue()/cancel_job() run, so an
        # unauthenticated call surfaces the same friendly "login first" hint as
        # the status path (which goes through get_job_status_sync).
        jq._require_auth()
        svc = jq.get_job_queue_service()
        response = svc.post(
            "jobs",
            json={
                "service": service,
                "model": model,
                "payload": payload if isinstance(payload, dict) else {},
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        return _api_result(jq.JobQueueService._normalize_response(response))

    return _guarded(_call)


def generation_job_status(job_id: str) -> dict:
    """Poll a job (GET /job-queue/jobs/{id}), normalized statuses."""
    if not job_id:
        return {"success": False, "error": "'job_id' is required"}

    def _call() -> dict:
        from mixar.modules.common.api.services.job_queue_service import (
            get_job_queue_service,
        )

        return _api_result(get_job_queue_service().get_job_status_sync(job_id))

    return _guarded(_call)


def generation_job_cancel(job_id: str) -> dict:
    """Cancel a job (DELETE /job-queue/jobs/{id})."""
    if not job_id:
        return {"success": False, "error": "'job_id' is required"}

    def _call() -> dict:
        from mixar.modules.common.api.services import job_queue_service as jq

        jq._require_auth()
        svc = jq.get_job_queue_service()
        response = svc.delete("jobs/{0}".format(job_id))
        return _api_result(jq.JobQueueService._normalize_response(response))

    return _guarded(_call)


# ── Generation catalog (cached client-side) ──────────────────────────────────

def generation_catalog(
    capability: Optional[str] = None, service: Optional[str] = None
) -> dict:
    """Read the cached generation catalog (capabilities → services → models)."""

    def _call() -> dict:
        from mixar.bootstrap import generation_catalog_cache as cache

        if not cache.is_loaded():
            return {
                "success": False,
                "error": "Generation catalog not loaded yet (requires login + fetch)",
                "loading": cache.is_cache_loading(),
                "cache_error": cache.get_cache_error(),
            }
        result: dict = {"success": True, "version": cache.get_catalog_version()}
        if service:
            result["service"] = cache.get_service(service)
            result["models"] = cache.get_models(service)
            result["default_model"] = cache.get_default_model_slug(service)
        elif capability:
            result["capability"] = cache.get_capability(capability)
            result["services"] = cache.get_services(capability)
        else:
            result["capabilities"] = cache.get_capabilities()
        return result

    return _guarded(_call)


# ── BYOK: bring-your-own-key provider integration ────────────────────────────

def byok_status() -> dict:
    """GET /agent/credentials — active state + masked key previews."""

    def _call() -> dict:
        from mixar.modules.common.api.services.agent_service import get_agent_service

        return _api_result(get_agent_service().get_credentials())

    return _guarded(_call)


def byok_models() -> dict:
    """GET /agent/models — provider/model catalog for BYOK."""

    def _call() -> dict:
        from mixar.modules.common.api.services.agent_service import get_agent_service

        return _api_result(get_agent_service().list_models())

    return _guarded(_call)


def byok_set(provider: str, model: str, api_key: str) -> dict:
    """PUT /agent/byok — store a provider key (validated server-side).

    The key transits directly from this loopback request to the configured
    backend over HTTPS; the bridge never logs or persists it.
    """
    if not provider or not model or not api_key:
        return {"success": False, "error": "'provider', 'model' and 'api_key' are required"}

    def _call() -> dict:
        from mixar.modules.common.api.services.agent_service import get_agent_service

        return _api_result(
            get_agent_service().save_credentials_all(provider, model, api_key)
        )

    return _guarded(_call)


def byok_remove() -> dict:
    """DELETE /agent/credentials/all — remove all BYOK config."""

    def _call() -> dict:
        from mixar.modules.common.api.services.agent_service import get_agent_service

        return _api_result(get_agent_service().delete_credentials_all())

    return _guarded(_call)
