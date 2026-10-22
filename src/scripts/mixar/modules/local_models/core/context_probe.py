# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Best-effort context window of a local OpenAI-compatible server.

Mixar's agent opens a turn at about 7K prompt tokens (its instructions and tool
schemas) and grows from there. A server whose window is smaller cuts every reply
for length before it can answer — prod MIXAR-BACKEND-1XF: an Ollama server at
8,192 tokens, three cut replies per turn. Each server reports its window its own
way, so every known shape is asked in turn; when none answers the window is
unknown and nothing is claimed.

Worker thread only. Never raises.
"""

import json
import re
import urllib.parse
import urllib.request
from typing import Optional

#: Below this the agent's replies get cut off (the AI Provider recap warns).
AGENT_MIN_CONTEXT = 32768
_TIMEOUT_S = 2.0
_NUM_CTX = re.compile(r"^\s*num_ctx\s+(\d+)\s*$", re.MULTILINE)


def _root(base_url: str) -> str:
    root = (base_url or "").strip().rstrip("/")
    return root[:-3] if root.endswith("/v1") else root


def _fetch(url: str, api_key: Optional[str], body: Optional[dict] = None) -> Optional[dict]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            payload = json.loads(response.read(1_000_000) or b"null")
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _positive(value) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _same_model(name, model: str) -> bool:
    name = str(name or "")
    return name == model or name.removesuffix(":latest") == model.removesuffix(":latest")


def _llama_cpp(root: str, model: str, api_key: Optional[str]) -> Optional[int]:
    props = _fetch(f"{root}/props", api_key) or {}
    settings = props.get("default_generation_settings") or {}
    return _positive(settings.get("n_ctx")) or _positive(props.get("n_ctx"))


def _lm_studio(root: str, model: str, api_key: Optional[str]) -> Optional[int]:
    entry = _fetch(f"{root}/api/v0/models/{urllib.parse.quote(model, safe='')}", api_key) or {}
    return _positive(entry.get("loaded_context_length"))


def _ollama(root: str, model: str, api_key: Optional[str]) -> Optional[int]:
    loaded = (_fetch(f"{root}/api/ps", api_key) or {}).get("models") or []
    for entry in loaded:
        if isinstance(entry, dict) and (_same_model(entry.get("name"), model)
                                        or _same_model(entry.get("model"), model)):
            if window := _positive(entry.get("context_length")):
                return window
    shown = _fetch(f"{root}/api/show", api_key, {"model": model}) or {}
    match = _NUM_CTX.search(str(shown.get("parameters") or ""))
    return int(match.group(1)) if match else None


def _vllm(root: str, model: str, api_key: Optional[str]) -> Optional[int]:
    for entry in (_fetch(f"{root}/v1/models", api_key) or {}).get("data") or []:
        if isinstance(entry, dict) and _same_model(entry.get("id"), model):
            return _positive(entry.get("max_model_len"))
    return None


def context_window(base_url: str, model: str, api_key: Optional[str] = None) -> Optional[int]:
    """The server's context window in tokens for ``model``, or None if unknown."""
    root = _root(base_url)
    if not root or not model:
        return None
    for probe in (_llama_cpp, _lm_studio, _ollama, _vllm):
        try:
            window = probe(root, model, api_key)
        except Exception:
            window = None
        if window:
            return window
    return None
