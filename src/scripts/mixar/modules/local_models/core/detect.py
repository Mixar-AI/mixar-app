# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Detect user-run local OpenAI-compatible servers (Ollama, LM Studio,
oMLX, stock llama.cpp) by probing their default ports on 127.0.0.1.

``probe_known_servers`` BLOCKS on the calling thread (worst case roughly
len(KNOWN_LOCAL_SERVERS) * timeout) — callers must run it on a worker
thread, never on Blender's main thread. Failure-silent by design: a port
that does not answer, answers garbage, or answers slowly is simply
omitted. No bpy imports.
"""

import json
import urllib.request
from typing import List

from mixar.config.logging_config import get_logger

from ..constants import KNOWN_LOCAL_SERVERS

logger = get_logger(__name__)

from .relay import _RefuseRedirects

# Test seam. Probe opener never follows redirects — a probed port must
# answer directly.
_urlopen = urllib.request.build_opener(_RefuseRedirects()).open

_MAX_PROBE_BYTES = 1024 * 1024


def _probe_one(kind: str, port: int, timeout: float):
    base_url = f"http://127.0.0.1:{port}"
    # Every server in KNOWN_LOCAL_SERVERS answers GET /v1/models
    # (Ollama included, alongside its native /api/tags).
    with _urlopen(f"{base_url}/v1/models", timeout=timeout) as response:
        status = getattr(response, "status", None) or response.getcode()
        if not 200 <= status < 300:
            return None
        payload = json.loads(response.read(_MAX_PROBE_BYTES))
    models = []
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                models.append(item["id"])
    return {"kind": kind, "port": port, "base_url": base_url, "models": models}


def probe_known_servers(timeout: float = 0.8) -> List[dict]:
    """Probe each known local server port; return the responders.

    Returns ``[{"kind", "port", "base_url", "models": [ids]}, ...]`` in
    KNOWN_LOCAL_SERVERS order. Blocking — call from a worker thread.
    """
    found = []
    for kind, port in KNOWN_LOCAL_SERVERS:
        try:
            result = _probe_one(kind, port, timeout)
        except Exception:
            continue  # silent: not running / not OpenAI-compatible
        if result is not None:
            found.append(result)
    return found
