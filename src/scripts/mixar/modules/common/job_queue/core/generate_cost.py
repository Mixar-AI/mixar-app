# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Billed credit cost for the Generate button.

Two sources, one number:

* The generation catalog already carries the billed (marked-up) cost for
  static services. Draw callbacks read that synchronously.
* ``image_gen`` (count) and ``video_gen`` (duration/resolution) are
  param-dependent. Those go through ``POST /job-queue/jobs/estimate`` on a
  0.7 s debounce, gated by a revision so a stale reply cannot land on a
  model the user has already left.

Draw callbacks never start the HTTP call themselves except by scheduling a
timer — a synchronous redraw here would steal the Generate click the way
Higgsfield's un-debounced estimator used to.
"""

from __future__ import annotations

import json
import math
import threading
from typing import Any, Optional


_DYNAMIC_SERVICES = frozenset({"image_gen", "video_gen", "depth_to_image"})
_ESTIMATE_DELAY_S = 0.7

_lock = threading.Lock()
_revision = 0
_state: dict[str, Any] = {
    "key": "",
    "credits": None,
    "status": "idle",  # idle | pending | ready | error
}


def format_credits_compact(credits: Any) -> str:
    """Short credit figure for tight button chrome (12, 1.2K, 3.4M)."""
    try:
        value = float(credits)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(value) or value < 0:
        return ""
    if value < 1000:
        if value == int(value):
            return str(int(value))
        return f"{value:.2f}".rstrip("0").rstrip(".")
    for threshold, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if value >= threshold:
            scaled = value / threshold
            if scaled >= 100:
                text = f"{scaled:.0f}"
            elif scaled >= 10:
                text = f"{scaled:.1f}".rstrip("0").rstrip(".")
            else:
                text = f"{scaled:.2f}".rstrip("0").rstrip(".")
            return f"{text}{suffix}"
    return str(int(value))


def catalog_cost(
    service_key: str = "",
    model_slug: str = "",
    feature_key: str = "",
) -> Optional[int]:
    """Billed catalog cost, or None when the catalog cannot answer."""
    try:
        from mixar.bootstrap.generation_catalog_cache import resolve_generate_cost

        return resolve_generate_cost(service_key, model_slug, feature_key)
    except Exception:
        return None


def generate_button_text(
    service_key: str = "",
    model_slug: str = "",
    feature_key: str = "",
    params: Optional[dict] = None,
) -> str:
    """``Generate`` or ``Generate · 12`` for the footer button.

    Dynamic services prefer a live estimate when it matches the current
    signature; otherwise they fall back to the catalog figure so the
    button is never blank while the estimate is in flight.
    """
    live = _live_estimate(service_key, model_slug, params)
    catalog = catalog_cost(service_key, model_slug, feature_key)
    credits = live if live is not None else catalog
    compact = format_credits_compact(credits)
    if compact:
        return f"Generate · {compact}"
    return "Generate"


def schedule_estimate_if_needed(
    service_key: str,
    model_slug: str = "",
    params: Optional[dict] = None,
    payload: Optional[dict] = None,
) -> None:
    """Debounce a live estimate for param-dependent services.

    Safe to call from a draw callback: it only registers a timer when the
    signature changed. Never tags a redraw here.
    """
    if service_key not in _DYNAMIC_SERVICES:
        return
    key = _signature(service_key, model_slug, params, payload)
    global _revision
    with _lock:
        if _state["key"] == key and _state["status"] in {"pending", "ready"}:
            return
        _revision += 1
        revision = _revision
        _state.update(key=key, credits=None, status="pending")

    def begin():
        with _lock:
            if revision != _revision:
                return None
        _start_estimate(revision, key, service_key, model_slug, params, payload)
        return None

    try:
        import bpy

        bpy.app.timers.register(begin, first_interval=_ESTIMATE_DELAY_S)
    except Exception:
        # Outside Blender (tests) the estimate is skipped; catalog cost remains.
        pass


def reset_estimate_state() -> None:
    """Drop in-flight estimates (logout / tests)."""
    global _revision
    with _lock:
        _revision += 1
        _state.update(key="", credits=None, status="idle")


def _live_estimate(
    service_key: str, model_slug: str, params: Optional[dict]
) -> Optional[int]:
    if service_key not in _DYNAMIC_SERVICES:
        return None
    key = _signature(service_key, model_slug, params, None)
    with _lock:
        if _state["key"] == key and _state["status"] == "ready":
            return _state["credits"]
    return None


def _signature(
    service_key: str,
    model_slug: str,
    params: Optional[dict],
    payload: Optional[dict],
) -> str:
    body = {
        "service": service_key or "",
        "model": model_slug or "",
        "params": params or {},
        "payload": _payload_fingerprint(payload),
    }
    return json.dumps(body, sort_keys=True, default=str)


def _payload_fingerprint(payload: Optional[dict]) -> dict:
    if not isinstance(payload, dict):
        return {}
    keep = {}
    for key in (
        "prompt",
        "params",
        "reference_video_s3_keys",
        "reference_image_s3_keys",
    ):
        if key in payload:
            keep[key] = payload[key]
    return keep


def _start_estimate(revision, key, service_key, model_slug, params, payload):
    try:
        from mixar.modules.common.api.services.job_queue_service import (
            get_job_queue_service,
        )
    except Exception:
        _mark_error(revision)
        return

    body_payload = dict(payload or {})
    if params is not None:
        body_payload.setdefault("params", params)
    if service_key == "video_gen" and "prompt" not in body_payload:
        # Seedance estimate requires a non-empty prompt; a placeholder is
        # enough to price duration/resolution without waiting for typing.
        body_payload.setdefault("prompt", "estimate")

    def on_success(response):
        credits = _credits_from_response(response)
        _mark_ready(revision, key, credits)

    def on_error(_error):
        _mark_error(revision)

    try:
        service = get_job_queue_service()
        service.estimate(
            job_type=service_key,
            model=model_slug or "",
            payload=body_payload,
            on_success=on_success,
            on_error=on_error,
        )
    except Exception:
        _mark_error(revision)


def _credits_from_response(response) -> Optional[int]:
    data = getattr(response, "data", None)
    if not isinstance(data, dict):
        return None
    inner = data.get("data", data)
    if not isinstance(inner, dict):
        return None
    try:
        credits = int(inner.get("credits"))
    except (TypeError, ValueError):
        return None
    return credits if credits > 0 else None


def _mark_ready(revision, key, credits):
    with _lock:
        if revision != _revision:
            return
        _state.update(key=key, credits=credits, status="ready")
    _request_redraw()


def _mark_error(revision):
    with _lock:
        if revision != _revision:
            return
        _state["status"] = "error"
    _request_redraw()


def _request_redraw():
    try:
        from mixar.modules.common.utils.platform_utils import trigger_ui_redraw

        trigger_ui_redraw()
    except Exception:
        pass
