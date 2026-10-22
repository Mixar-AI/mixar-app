# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Keep local filesystem paths out of every model name that leaves the app.

An unaliased llama-server reports the absolute path of its ``.gguf`` as its
model id (``/v1/models`` and every completion's ``model``). That path names
the user's OS account and directory layout, so it must never become the BYOK
``model`` sent to the backend. The managed server is started with
``--alias <model id>`` (see ``server_supervisor.build_server_argv``); for
user-run servers :func:`safe_model_name` reduces a path to its basename.

Plain ids with a slash (LM Studio ``qwen/qwen3-8b``, Ollama
``hf.co/user/repo:tag``) are ids, not paths, and pass through unchanged. The
relay also sanitizes the response's model field before it leaves the app.
Pure stdlib, no bpy.
"""

import json
import re

# A name with a directory component ending in one of these is a file on disk.
MODEL_FILE_SUFFIXES = (".gguf", ".ggml", ".bin", ".safetensors")

_DRIVE_LETTER = re.compile(r"^[A-Za-z]:")
_FILE_URI = re.compile(r"^file:/*", re.IGNORECASE)
_PATH_PREFIXES = ("/", "~", "./", "../")
_HUB_PREFIXES = ("hf.co/", "huggingface.co/")


def _unquote(name: str) -> str:
    if len(name) >= 2 and name[0] in ('"', "'") and name[-1] == name[0]:
        return name[1:-1]
    return name


def is_path_like(model: str) -> bool:
    """True when ``model`` looks like a local filesystem path."""
    name = _unquote((model or "").strip())
    if not name:
        return False
    if "\\" in name or _DRIVE_LETTER.match(name) or _FILE_URI.match(name):
        return True
    if name.startswith(_PATH_PREFIXES):
        return True
    # Ollama accepts a complete GGUF filename as the tag of a Hub model:
    # hf.co/owner/repo:filename.gguf. It must retain the repository prefix.
    if name.startswith(_HUB_PREFIXES):
        return False
    return "/" in name and name.lower().endswith(MODEL_FILE_SUFFIXES)


def safe_model_name(model: str) -> str:
    """``model`` unchanged, or its last path segment when it is a path."""
    name = (model or "").strip()
    if not is_path_like(name):
        return name
    name = _DRIVE_LETTER.sub("", _FILE_URI.sub("", _unquote(name)))
    segments = [part for part in re.split(r"[\\/]+", name) if part]
    base = segments[-1] if segments else ""
    if not base or base in (".", "..", "~"):
        return "local-model"
    return base


def safe_response_body(body: str) -> str:
    """Sanitize only a completion's model field, preserving generated content.

    A user-run server can still echo its GGUF path after we save a basename.
    Malformed/non-JSON responses and ordinary model ids pass through verbatim.
    """
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):
        return body
    if not isinstance(data, dict) or not isinstance(data.get("model"), str):
        return body
    model = safe_model_name(data["model"])
    if model == data["model"]:
        return body
    data["model"] = model
    return json.dumps(data)
