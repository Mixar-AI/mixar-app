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

``probe_vision`` answers a different question: does *one specific model*
on a user-run server accept image input? Third-party servers (Strata,
custom llama.cpp builds, vLLM…) are not in KNOWN_LOCAL_SERVERS, so nothing
else can tell us, and guessing wrong costs the user their 3D screenshots.
See the vision section at the bottom.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional

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


# ---------------------------------------------------------------------------
# Vision-capability probe (one model on a user-run server)
# ---------------------------------------------------------------------------

# A real 1x1 PNG (68 bytes, valid signature + chunk CRCs) sent as a data URL.
# Tiny on purpose: a cold server still has to load the model, not decode a
# photo, and the request body stays well under any server-side limit.
_PIXEL_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgAAIAAAU"
    "AAXpeqz8AAAAASUVORK5CYII="
)

# How servers say "this model has no image projector" when an image is
# rejected (llama.cpp, Ollama, LM Studio, vLLM all phrase it differently).
# Matched against the lowercased error body of a rejected image request.
_VISION_NEGATIVE_MARKERS = (
    "does not support image",
    "do not support image",
    "not support image",
    "images are not supported",
    "image input",
    "image inputs",
    "vision",
    "multimodal",
    "mmproj",
    "projector",
)

# Capability / modality names that mean "images accepted" when read from
# server metadata (as opposed from an error body).
_VISION_POSITIVE_MARKERS = ("image", "vision", "multimodal", "mmproj", "projector")

# Names that are vision models in practice. Last resort only, and only in the
# positive direction: a wrong True costs one rejected image turn, a wrong
# False silently disables visual feedback, so an unknown name stays unknown.
_VISION_NAME_RE = re.compile(
    r"(vision|multimodal|minicpm-v|internvl|pixtral|llava|moondream"
    r"|phi-?vision|glm-?4v|nanovlm|fuyu|-vl[-\d]|-vl$|\bvl\d*\b)",
    re.IGNORECASE,
)

# The image probe loads the model on a cold server, so it gets a generous
# budget; the metadata reads are static files and answer fast.
VISION_PROBE_TIMEOUT_S = 6.0
VISION_META_TIMEOUT_S = 2.0


def _request_headers(api_key: Optional[str]) -> dict:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _exchange(url: str, api_key: Optional[str], payload=None,
              timeout: float = VISION_META_TIMEOUT_S):
    """One JSON request/response. Returns ``(status, body_text, parsed)``.

    HTTP errors are answers, not failures: their status and body come back
    too. Transport-level problems raise for the caller to swallow.
    """
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    headers = _request_headers(api_key)
    if data:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with _urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", None) or response.getcode()
            body = response.read(_MAX_PROBE_BYTES).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:  # a real answer with an error status
        status = exc.code
        try:
            body = exc.read(_MAX_PROBE_BYTES).decode("utf-8", "replace")
        except Exception:
            body = ""
    try:
        parsed = json.loads(body) if body else None
    except Exception:
        parsed = None
    return status, body, parsed


def _get_json(url: str, api_key: Optional[str],
              timeout: float = VISION_META_TIMEOUT_S):
    """GET *url* and return its parsed JSON body, or None on any failure."""
    try:
        status, _body, parsed = _exchange(url, api_key, timeout=timeout)
    except Exception:
        return None
    return parsed if 200 <= status < 300 else None


def _chat_base(base_url: str) -> str:
    """``http://host:port`` → ``http://host:port/v1`` (idempotent)."""
    base = (base_url or "").rstrip("/")
    return base if base.endswith("/v1") else f"{base}/v1"


def _rejects_images(body: str) -> bool:
    text = (body or "").lower()
    return any(marker in text for marker in _VISION_NEGATIVE_MARKERS)


def _verdict_from_capabilities(value) -> Optional[bool]:
    """True/False from a list/str/dict of modality or capability names."""
    if isinstance(value, dict):
        value = list(value.keys())
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return None
    names = [str(item).lower() for item in value]
    if any(marker in name for name in names
           for marker in _VISION_POSITIVE_MARKERS):
        return True
    if any(name in ("text", "text-only", "completion", "embed") for name in names):
        return False
    return None


def _probe_chat_completion(base_url: str, model_id: str,
                           api_key: Optional[str], timeout: float):
    """Primary signal: send a 1x1 image and read how the server reacts.

    A vision model answers (True); a text-only model rejects the image
    specifically (False); anything else — auth wall, server error, missing
    endpoint, timeout — proves nothing (None).
    """
    payload = {
        "model": model_id,
        "max_tokens": 1,
        "stream": False,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "Reply with the single word: ok"},
                {"type": "image_url", "image_url": {"url": _PIXEL_PNG_DATA_URL}},
            ],
        }],
    }
    try:
        status, body, _parsed = _exchange(
            f"{_chat_base(base_url)}/chat/completions", api_key, payload, timeout)
    except Exception as exc:
        logger.debug("Vision probe request failed: %s", exc)
        return None
    if 200 <= status < 300:
        return True
    if status in (400, 404, 409, 415, 422) and _rejects_images(body):
        return False
    return None


def _probe_metadata(base_url: str, model_id: str, api_key: Optional[str],
                    timeout: float):
    """Fallback signals: capability metadata the server already publishes."""
    base = base_url.rstrip("/")

    # llama.cpp /v1/models/<id> and LM Studio expose modalities/projector.
    detail = _get_json(
        f"{_chat_base(base)}/models/{urllib.parse.quote(model_id, safe='')}",
        api_key, timeout)
    if isinstance(detail, dict):
        for key in ("supported_modalities", "input_modalities", "modalities",
                    "capabilities"):
            verdict = _verdict_from_capabilities(detail.get(key))
            if verdict is not None:
                return verdict
        if "mmproj_file" in detail or "projector_path" in detail:
            return bool(detail.get("mmproj_file") or detail.get("projector_path"))

    # Stock llama.cpp server: /props carries the projector path (empty = none).
    props = _get_json(f"{base}/props", api_key, timeout)
    if isinstance(props, dict) and "projector_path" in props:
        return bool(props.get("projector_path"))

    # Ollama's native inspect endpoint: capabilities list "vision" when it fits.
    try:
        status, _body, shown = _exchange(
            f"{base}/api/show", api_key, {"name": model_id}, timeout)
    except Exception:
        status, shown = 0, None
    if isinstance(shown, dict) and 200 <= status < 300:
        verdict = _verdict_from_capabilities(shown.get("capabilities"))
        if verdict is not None:
            return verdict
        info = shown.get("model_info") or shown.get("details") or {}
        if isinstance(info, dict) and any(
                "projector" in str(key).lower() for key in info):
            return True
    return None


def probe_vision(base_url: str, model_id: str, api_key: Optional[str] = None,
                 timeout: float = VISION_PROBE_TIMEOUT_S,
                 metadata_timeout: float = VISION_META_TIMEOUT_S):
    """Does ``model_id`` on ``base_url`` accept image input?

    Returns True/False when the server gave a usable answer, **None** when
    every signal was inconclusive — callers keep their conservative default
    in that case. Blocking (the image probe waits for a cold model to load):
    run it on a worker thread.
    """
    base = (base_url or "").strip().rstrip("/")
    model_id = (model_id or "").strip()
    if not base or not model_id:
        return None
    verdict = _probe_chat_completion(base, model_id, api_key, timeout)
    if verdict is None:
        verdict = _probe_metadata(base, model_id, api_key, metadata_timeout)
    if verdict is None and _VISION_NAME_RE.search(model_id):
        logger.debug(
            "Vision probe inconclusive for %s; the name looks like a vision "
            "model", model_id)
        return True
    logger.debug("Vision probe %s @ %s → %s", model_id, base, verdict)
    return verdict

