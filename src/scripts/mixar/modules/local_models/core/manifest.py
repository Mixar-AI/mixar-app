# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""On-disk manifest of the local-models install state.

One JSON file (``paths.manifest_path()``) records what is installed and
how the managed server is configured:

- ``runtime``: pinned tag + the release asset that was proven to work,
  and whether it finished extracting (``ready``);
- ``models``: per-model ``files_ready`` flags;
- ``active_model_id``: the model the user last chose;
- ``port``: the last llama-server port (reused while still free);
- ``api_token``: minted once (``secrets.token_urlsafe(24)``) — the
  localhost server requires it, so other local processes cannot ride on
  the managed server;
- ``registered``: snapshot of what was last registered with the backend
  ({base_url, model_id, supports_vision}) so Stage 2 can detect drift.

Writes are atomic (mkstemp + fsync + os.replace, same idiom as
``bootstrap/generation_catalog/storage.py``) and every read/modify/write
runs under one module lock, so any thread may call these helpers.
"""

import json
import os
import secrets
import tempfile
import threading
from typing import Any, Dict, Optional

from mixar.config.logging_config import get_logger

from . import paths

logger = get_logger(__name__)

_lock = threading.RLock()

_DEFAULTS: Dict[str, Any] = {
    "version": 1,
    "runtime": {"tag": None, "variant_asset": None, "ready": False},
    "models": {},
    "active_model_id": None,
    "port": None,
    "api_token": None,
    "registered": None,
}


def _read() -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    path = paths.manifest_path()
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                data = loaded
    except Exception as exc:
        logger.warning("Local models manifest read failed: %s", exc)
    # Deep-copy the defaults: handing out _DEFAULTS' nested dicts would
    # let a set_* call mutate the template for every later read.
    merged = json.loads(json.dumps(_DEFAULTS))
    merged.update(data)
    if not isinstance(merged.get("models"), dict):
        merged["models"] = {}
    if not isinstance(merged.get("runtime"), dict):
        merged["runtime"] = json.loads(json.dumps(_DEFAULTS["runtime"]))
    return merged


def _write(data: Dict[str, Any]) -> None:
    path = paths.manifest_path()
    temp_path = None
    try:
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            prefix=".manifest.", suffix=".tmp", dir=directory
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass


def load() -> Dict[str, Any]:
    """A defensive copy of the full manifest."""
    with _lock:
        return json.loads(json.dumps(_read()))


def update(**fields: Any) -> Dict[str, Any]:
    """Atomically merge top-level *fields* into the manifest."""
    with _lock:
        data = _read()
        data.update(fields)
        _write(data)
        return data


# -- runtime -----------------------------------------------------------------

def get_runtime() -> Dict[str, Any]:
    with _lock:
        return dict(_read()["runtime"])


def set_runtime(tag: str, variant_asset: str, ready: bool) -> None:
    with _lock:
        data = _read()
        data["runtime"] = {
            "tag": tag, "variant_asset": variant_asset, "ready": bool(ready),
        }
        _write(data)


# -- models ------------------------------------------------------------------

def get_model_state(model_id: str) -> Dict[str, Any]:
    with _lock:
        return dict(_read()["models"].get(model_id) or {})


def set_model_files_ready(model_id: str, files_ready: bool) -> None:
    with _lock:
        data = _read()
        entry = dict(data["models"].get(model_id) or {})
        entry["files_ready"] = bool(files_ready)
        data["models"][model_id] = entry
        _write(data)


def ready_model_ids() -> tuple:
    with _lock:
        models = _read()["models"]
        return tuple(
            model_id for model_id, entry in models.items()
            if isinstance(entry, dict) and entry.get("files_ready")
        )


# -- active model / port -----------------------------------------------------

def get_active_model_id() -> Optional[str]:
    with _lock:
        return _read()["active_model_id"]


def set_active_model_id(model_id: Optional[str]) -> None:
    update(active_model_id=model_id)


def get_port() -> Optional[int]:
    with _lock:
        port = _read()["port"]
        return int(port) if isinstance(port, int) else None


def set_port(port: Optional[int]) -> None:
    update(port=port)


# -- API token ---------------------------------------------------------------

def get_api_token() -> str:
    """The server API token — minted exactly once, then persisted."""
    with _lock:
        data = _read()
        token = data.get("api_token")
        if isinstance(token, str) and token:
            return token
        token = secrets.token_urlsafe(24)
        data["api_token"] = token
        _write(data)
        return token


# -- backend registration snapshot -------------------------------------------

def get_registered() -> Optional[Dict[str, Any]]:
    with _lock:
        registered = _read()["registered"]
        return dict(registered) if isinstance(registered, dict) else None


def set_registered(base_url: Optional[str], model_id: Optional[str],
                   supports_vision: Optional[bool]) -> None:
    """Snapshot what was last registered with the backend (None clears)."""
    if base_url is None:
        update(registered=None)
        return
    update(registered={
        "base_url": base_url,
        "model_id": model_id,
        "supports_vision": bool(supports_vision),
    })
