# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Support diagnostics bundle — session facts, never secrets.

Higgsfield ships a one-click dump of version/environment/queue state so a
report does not start with "which build is this?". Mixar's equivalent is a
JSON document: Mixar and Blender versions, OS, GPU if known, catalog
version, signed-in flag, and a lightweight queue snapshot. Tokens, API
keys, prompts, file paths, and scene contents stay out.
"""

from __future__ import annotations

import json
import platform
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List


_SECRET_KEYS = (
    "token",
    "secret",
    "password",
    "key",
    "authorization",
    "cookie",
)


def _mixar_version() -> str:
    try:
        from mixar.modules.common.updates.core.update_checker import (
            get_runtime_version,
        )

        return str(get_runtime_version() or "")
    except Exception:
        pass
    try:
        from mixar.modules.common.updates.core.update_checker import (
            get_current_version,
        )

        return str(get_current_version() or "")
    except Exception:
        return ""


def _blender_version() -> str:
    try:
        import bpy

        return str(getattr(bpy.app, "version_string", "") or "")
    except Exception:
        return ""


def _gpu_name() -> str:
    try:
        import bpy

        return str(getattr(bpy.context.preferences.system, "compute_device_type", "") or "")
    except Exception:
        return ""


def _signed_in() -> bool:
    try:
        from mixar.modules.auth.core.auth import get_access_token

        return bool(get_access_token())
    except Exception:
        return False


def _catalog_version() -> str:
    try:
        from mixar.bootstrap.generation_catalog_cache import get_catalog_version

        return str(get_catalog_version() or "")
    except Exception:
        return ""


def _queue_snapshot() -> List[Dict[str, Any]]:
    jobs: List[Dict[str, Any]] = []
    try:
        from mixar.modules.common.job_queue.core.queue_manager import all_queues

        for queue in all_queues():
            snapshot = queue.snapshot() if hasattr(queue, "snapshot") else ()
            for job in snapshot:
                jobs.append({
                    "feature_key": getattr(queue, "feature_key", "") or "",
                    "state": str(getattr(job, "state", "") or ""),
                    "service": str(getattr(job, "service", "") or ""),
                    "model": str(getattr(job, "model", "") or ""),
                    "label": str(
                        getattr(job, "display_label", "")
                        or getattr(job, "label", "")
                        or ""
                    ),
                })
    except Exception:
        pass
    return jobs[:50]


def build_diagnostics() -> Dict[str, Any]:
    """Return a JSON-serializable support dump with no secrets."""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mixar_version": _mixar_version(),
        "blender_version": _blender_version(),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "gpu": _gpu_name(),
        "signed_in": _signed_in(),
        "catalog_version": _catalog_version(),
        "queue": _queue_snapshot(),
    }


def diagnostics_text() -> str:
    return json.dumps(build_diagnostics(), indent=2, sort_keys=True)


def contains_secret(text: str) -> bool:
    lowered = (text or "").lower()
    return any(key in lowered for key in _SECRET_KEYS)
