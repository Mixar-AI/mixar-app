# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent-facing Publish to Web (backend tool scripts call these).

A tool script reads ``__PARAMS__`` and prints the result::

    from mixar.modules.web_publish.core.agent_api import start_publish
    print("__RESULT__" + json.dumps(start_publish(__PARAMS__)))

Both functions run on Blender's main thread (the agent executor) and return
JSON-safe dicts; neither raises. ``start_publish`` exports synchronously
(seconds) and returns as soon as the upload thread starts; the agent then
polls ``publish_status``. Every string is English and untranslated (agent
text is never localized), and no local path ever appears. Contract:
``docs/modules/web-publish.md`` § Agent API.
"""

from __future__ import annotations

from typing import Any, Dict

from mixar.modules.web_publish.core.publish_state import (
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_EXPORTING,
    STATUS_FINALIZING,
    STATUS_IDLE,
    STATUS_UPLOADING,
    format_message,
    get_publish_state,
)

AGENT_STATUS = {
    STATUS_EXPORTING: "exporting",
    STATUS_UPLOADING: "uploading",
    STATUS_FINALIZING: "uploading",
    STATUS_DONE: "ready",
    STATUS_ERROR: "failed",
    STATUS_CANCELLED: "cancelled",
}


def _flag(params: Dict[str, Any], key: str, default=None):
    value = params.get(key, default)
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _text(params: Dict[str, Any], key: str):
    value = params.get(key)
    return None if value is None else str(value)


def start_publish(params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Publish the scene the script runs in.

    params: ``title`` (str, optional — the panel title, else derived from the
    scene name), ``description`` (str, optional), ``update_existing`` (bool,
    default False — publish a new revision at the scene's existing link),
    ``include_animation`` (bool, optional — the panel setting, default True),
    ``visibility`` (``"public"``/``"unlisted"``, optional — a new publish
    defaults to the panel setting; a new version without it keeps the
    site's current access).

    Returns ``{"publish_id": str, "status": "started"}``; a refusal (signed
    out, already publishing, nothing visible, export failure) returns
    ``{"publish_id": None, "status": "failed", "error": str}``.
    """
    params = dict(params or {})
    try:
        import bpy

        from mixar.modules.web_publish.core.pipeline import begin_publish

        outcome = begin_publish(
            bpy.context,
            title=_text(params, "title"),
            description=_text(params, "description"),
            update_existing=bool(_flag(params, "update_existing", False)),
            include_animation=_flag(params, "include_animation", None),
            visibility=_text(params, "visibility"),
            via="agent",
        )
    except Exception as exc:  # noqa: BLE001 - the agent always gets a dict
        return {"publish_id": None, "status": "failed",
                "error": f"Publish could not start ({exc.__class__.__name__})"}
    if not outcome.get("ok"):
        return {"publish_id": None, "status": "failed",
                "error": format_message(outcome.get("error", ""), outcome.get("error_args"))}
    return {"publish_id": outcome["publish_id"], "status": "started"}


def publish_status(publish_id: str) -> Dict[str, Any]:
    """Progress of ``publish_id`` (from ``start_publish``).

    Returns ``{"status": "exporting"|"uploading"|"ready"|"failed"|"cancelled",
    "progress": float 0..1, "share_url": str|None, "slug": str|None,
    "error": str|None, "warning": str|None}``. An unknown id (never started
    here, or evicted after newer publishes) reports ``failed`` with an error.
    """
    if isinstance(publish_id, dict):  # tolerate __PARAMS__ passed whole
        publish_id = publish_id.get("publish_id", "")
    found = get_publish_state().lookup(str(publish_id or ""))
    if found is None:
        return {"status": "failed", "progress": 0.0, "share_url": None, "slug": None,
                "error": "Unknown publish_id", "warning": None}
    progress, result = found
    status = AGENT_STATUS.get(progress.status, "exporting" if progress.status != STATUS_IDLE
                              else "failed")
    ready = status == "ready"
    failed = status in ("failed", "cancelled")
    from mixar.modules.web_publish.core.links import safe_share_link

    safe_links = [safe_share_link(url) for url in (result.share_url, result.viewer_url) if url]
    link = next((url for url in safe_links if url), None)
    return {
        "status": status,
        "progress": 1.0 if ready else round(float(progress.progress), 3),
        "share_url": link if ready else None,
        "slug": (result.slug or None) if ready else None,
        "error": (progress.error_text or None) if failed else None,
        "warning": progress.warning or None,
    }
