# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ensure the pinned llama.cpp runtime and model files are installed.

Blocking helpers meant for a background worker thread (Stage 2 wraps them
in the daemon-thread + main-thread-timer pattern). No bpy imports.

Progress contract: ``progress_cb(label, transferred, total)`` is invoked
on the calling thread — *label* is the file being transferred (or
``"extract"`` while unpacking, with 0/0), *total* may be 0 when unknown.
``cancel_cb() -> bool`` is polled throughout; cancelling raises
``download.DownloadCancelled`` and keeps partial ``.part`` files for a
later resume.
"""

import os
from typing import Callable, Dict, List, Optional

from mixar.config.logging_config import get_logger

from ..constants import (
    LLAMA_CPP_TAG,
    LOG_PREFIX,
    RUNTIME_ASSETS,
    RUNTIME_DOWNLOAD_URL_TEMPLATE,
)
from . import catalog, manifest, paths, platform_info
from .archive import ArchiveError, safe_extract
from .download import DownloadCancelled, DownloadError, download_file

logger = get_logger(__name__)

ProgressCb = Optional[Callable[[str, int, int], None]]
CancelCb = Optional[Callable[[], bool]]


class LocalRuntimeError(Exception):
    """Runtime/model provisioning failed. ``user_message`` is UI-safe."""

    def __init__(self, message, user_message=""):
        super().__init__(message)
        self.user_message = user_message or "Local model setup failed"


# ---------------------------------------------------------------------------
# Runtime (llama-server)
# ---------------------------------------------------------------------------

def runtime_candidates(*, exclude_variants=()) -> List[dict]:
    """This platform's candidate builds, manifest-proven variant first."""
    key = platform_info.platform_key()
    candidates = [
        dict(spec) for spec in RUNTIME_ASSETS.get(key, ())
        if spec["variant"] not in set(exclude_variants)
    ]
    proven = manifest.get_runtime()
    if proven.get("ready") and proven.get("tag") == LLAMA_CPP_TAG:
        candidates.sort(
            key=lambda spec: spec["asset"] != proven.get("variant_asset")
        )
    return candidates


def next_fallback_variant(current_variant: str) -> Optional[str]:
    """The next untried variant after *current_variant*, if any."""
    specs = RUNTIME_ASSETS.get(platform_info.platform_key(), ())
    seen_current = False
    for spec in specs:
        if seen_current:
            return spec["variant"]
        if spec["variant"] == current_variant:
            seen_current = True
    return None


def server_binary_path(variant: str) -> Optional[str]:
    """Path of the installed llama-server binary for *variant*, or None."""
    root = paths.runtime_dir(LLAMA_CPP_TAG, variant)
    for name in ("llama-server", "llama-server.exe"):
        candidate = os.path.join(root, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def _install_candidate(spec: dict, progress_cb: ProgressCb,
                       cancel_cb: CancelCb) -> str:
    url = RUNTIME_DOWNLOAD_URL_TEMPLATE.format(
        tag=LLAMA_CPP_TAG, asset=spec["asset"]
    )
    archive_path = os.path.join(paths.base_dir(), "downloads", spec["asset"])

    def _on_progress(transferred, total, _attempt):
        if progress_cb is not None:
            progress_cb(spec["asset"], transferred, total)

    download_file(
        url, archive_path,
        expected_sha256=spec["sha256"], expected_size=spec["size"],
        on_progress=_on_progress, should_cancel=cancel_cb,
    )
    if progress_cb is not None:
        progress_cb("extract", 0, 0)
    dest = paths.runtime_dir(LLAMA_CPP_TAG, spec["variant"])
    safe_extract(archive_path, dest)
    binary = server_binary_path(spec["variant"])
    if binary is None:
        raise LocalRuntimeError(
            f"llama-server missing after extracting {spec['asset']}"
        )
    try:
        os.remove(archive_path)
    except OSError:
        pass
    manifest.set_runtime(LLAMA_CPP_TAG, spec["asset"], True)
    logger.info("%s runtime ready: %s", LOG_PREFIX, binary)
    return binary


def ensure_runtime(progress_cb: ProgressCb = None, cancel_cb: CancelCb = None,
                   *, exclude_variants=()) -> str:
    """Return the path to a ready llama-server, installing if needed.

    Iterates this platform's candidate assets in order (a previously
    proven variant first), skipping *exclude_variants* — the supervisor's
    ``retry_fallback`` path passes the failed variant here to force the
    next build. Blocking; call from a worker thread.
    """
    candidates = runtime_candidates(exclude_variants=exclude_variants)
    if not candidates:
        raise LocalRuntimeError(
            f"No llama.cpp build for platform {platform_info.platform_key()!r}",
            "Local models are not supported on this platform",
        )
    for spec in candidates:
        binary = server_binary_path(spec["variant"])
        if binary is not None:
            manifest.set_runtime(LLAMA_CPP_TAG, spec["asset"], True)
            return binary

    last_error: Optional[Exception] = None
    for spec in candidates:
        try:
            return _install_candidate(spec, progress_cb, cancel_cb)
        except DownloadCancelled:
            raise
        except (DownloadError, ArchiveError, LocalRuntimeError, OSError) as exc:
            last_error = exc
            logger.warning(
                "%s runtime candidate %s failed: %s",
                LOG_PREFIX, spec["variant"], exc,
            )
    raise LocalRuntimeError(
        f"All runtime candidates failed: {last_error}",
        getattr(last_error, "user_message", "") or "Could not install the local AI runtime",
    )


# ---------------------------------------------------------------------------
# Models (GGUF files)
# ---------------------------------------------------------------------------

def model_file_paths(model_id: str) -> Dict[str, Optional[str]]:
    """Expected on-disk locations: {"gguf": path, "mmproj": path|None}."""
    entry = catalog.get_model(model_id)
    if entry is None:
        raise LocalRuntimeError(f"Unknown model id: {model_id!r}")
    root = paths.model_dir(model_id)
    mmproj = entry.get("mmproj")
    return {
        "gguf": os.path.join(root, entry["file"]["name"]),
        "mmproj": os.path.join(root, mmproj["name"]) if mmproj else None,
    }


def model_files_present(model_id: str) -> bool:
    """True when every required file exists with its pinned size."""
    entry = catalog.get_model(model_id)
    if entry is None:
        return False
    root = paths.model_dir(model_id)
    for spec in catalog.required_files(model_id):
        target = os.path.join(root, spec["name"])
        try:
            if os.path.getsize(target) != spec["size"]:
                return False
        except OSError:
            return False
    return True


def ensure_model(model_id: str, progress_cb: ProgressCb = None,
                 cancel_cb: CancelCb = None) -> Dict[str, Optional[str]]:
    """Download (or verify) a model's GGUF (+ mmproj), sha-pinned.

    Returns :func:`model_file_paths`. Blocking; call from a worker thread.
    Files already present at their pinned size are not re-downloaded.
    """
    entry = catalog.get_model(model_id)
    if entry is None:
        raise LocalRuntimeError(f"Unknown model id: {model_id!r}")
    root = paths.model_dir(model_id)
    for spec in catalog.required_files(model_id):
        target = os.path.join(root, spec["name"])
        try:
            if os.path.getsize(target) == spec["size"]:
                continue
        except OSError:
            pass

        def _on_progress(transferred, total, _attempt, _name=spec["name"]):
            if progress_cb is not None:
                progress_cb(_name, transferred, total)

        download_file(
            spec["url"], target,
            expected_sha256=spec["sha256"], expected_size=spec["size"],
            on_progress=_on_progress, should_cancel=cancel_cb,
        )
    manifest.set_model_files_ready(model_id, True)
    logger.info("%s model ready: %s", LOG_PREFIX, model_id)
    return model_file_paths(model_id)
