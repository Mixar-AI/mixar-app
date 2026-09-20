# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Download orchestration: worker thread + main-thread pump + sticky toast.

``start_download(model_id)`` (MAIN THREAD) spawns a daemon worker running
the blocking ``runtime.ensure_runtime`` + ``runtime.ensure_model``; the
worker only writes plain ints/strings onto the module-level ``_dl`` state
object (never bpy). A self-gating 0.5 s ``bpy.app.timers`` pump mirrors
that state into the ``wm.mixar_local_dl_*`` props and ONE sticky toast
(stable id ``LOCAL_MODEL_TOAST_ID``) following the enqueue_toast
discipline: text derived from live state, re-pushed only when it changes,
user dismissal (``store.contains``) respected until the next download,
one terminal push ("Local model ready" / error) or dismiss (cancel).
"""

import os
import threading

from mixar.config.logging_config import get_logger

from ..constants import LOCAL_MODEL_TOAST_ID, LOG_PREFIX
from . import catalog, runtime
from .download import DownloadCancelled

logger = get_logger(__name__)

_PUMP_INTERVAL_S = 0.5


class _DownloadState:
    """Plain-attribute state the worker writes and the pump reads."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.active = False
        self.model_id = ""
        self.label = ""            # human label of the model
        self.file_label = ""       # "local AI runtime" | model label | "extract"
        self.pct = 0
        self.done = False
        self.cancelled = False
        self.error = ""            # UI-safe message


_dl = _DownloadState()
_cancel = threading.Event()
_pump_registered = False
_last_toast_key = ""
_toast_suppressed = False


# ---------------------------------------------------------------------------
# Shared main-thread helpers (also imported by orchestrator.py)
# ---------------------------------------------------------------------------

def wm_or_none():
    """The live WindowManager, or None. Main thread only."""
    try:
        import bpy
        return bpy.context.window_manager
    except Exception:
        return None


def redraw() -> None:
    try:
        from mixar.modules.common.utils.platform_utils import trigger_ui_redraw
        trigger_ui_redraw()
    except Exception:
        pass


def invalidate_byok_items() -> None:
    """Model list state changed (downloaded/removed) — refresh the BYOK
    dialog's cached dropdown items. Lazy + guarded (cross-module)."""
    try:
        from mixar.modules.byok.core import local_provider
        local_provider.refresh_model_items()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

def start_download(model_id: str):
    """Begin downloading the runtime + *model_id*. MAIN THREAD ONLY.

    Returns (ok, ui_error). Refuses while another download is active.
    """
    global _toast_suppressed
    entry = catalog.get_model(model_id)
    if entry is None:
        return False, "Unknown local model"
    if _dl.active:
        return False, "Another download is already in progress"

    _dl.reset()
    _dl.active = True
    _dl.model_id = model_id
    _dl.label = entry["label"]
    _cancel.clear()
    _toast_suppressed = False

    threading.Thread(
        target=_download_worker, args=(model_id, entry["label"]),
        daemon=True, name="MixarLocalModelDownload",
    ).start()
    _ensure_pump()
    return True, None


def cancel_download() -> None:
    """Ask the worker to stop (the .part files are kept for resume)."""
    _cancel.set()


def download_in_progress() -> bool:
    return _dl.active


def download_snapshot() -> dict:
    """Plain values for UI mirrors (safe from the main thread)."""
    return {
        "active": _dl.active,
        "model_id": _dl.model_id,
        "label": _dl.label,
        "file_label": _dl.file_label,
        "pct": _dl.pct,
        "error": _dl.error,
    }


# ---------------------------------------------------------------------------
# Worker (daemon thread — NO bpy)
# ---------------------------------------------------------------------------

def _download_worker(model_id: str, label: str) -> None:
    per_file: dict = {}

    # Planned model bytes = files not already complete on disk.
    planned = 0
    try:
        from . import paths
        root = paths.model_dir(model_id)
        for spec in catalog.required_files(model_id):
            target = os.path.join(root, spec["name"])
            try:
                if os.path.getsize(target) == spec["size"]:
                    continue
            except OSError:
                pass
            planned += spec["size"]
    except Exception:
        planned = 0

    def _runtime_progress(file_label, transferred, total):
        if file_label == "extract":
            _dl.file_label = "extract"
            return
        _dl.file_label = "local AI runtime"
        _dl.pct = int(transferred * 100 / total) if total else 0

    def _model_progress(file_label, transferred, total):
        _dl.file_label = label
        per_file[file_label] = transferred
        if planned:
            _dl.pct = min(99, int(sum(per_file.values()) * 100 / planned))
        elif total:
            _dl.pct = int(transferred * 100 / total)

    def _cancelled() -> bool:
        return _cancel.is_set()

    try:
        runtime.ensure_runtime(_runtime_progress, _cancelled)
        _dl.pct = 0
        runtime.ensure_model(model_id, _model_progress, _cancelled)
        _dl.pct = 100
        _dl.done = True
        logger.info("%s download complete: %s", LOG_PREFIX, model_id)
    except DownloadCancelled:
        _dl.cancelled = True
        logger.info("%s download cancelled: %s", LOG_PREFIX, model_id)
    except Exception as exc:  # noqa: BLE001 - worker must never raise
        _dl.error = getattr(exc, "user_message", "") or "Local model setup failed"
        logger.error("%s download failed: %s", LOG_PREFIX, exc, exc_info=True)
    finally:
        _dl.active = False


# ---------------------------------------------------------------------------
# Pump (main-thread bpy timer)
# ---------------------------------------------------------------------------

def _ensure_pump() -> None:
    """Register the 0.5 s mirror pump. MAIN THREAD ONLY. Self-gating."""
    global _pump_registered
    if _pump_registered:
        return
    try:
        import bpy
        bpy.app.timers.register(_pump, first_interval=0.0, persistent=True)
        _pump_registered = True
    except Exception as exc:
        logger.warning("%s could not start progress pump: %s", LOG_PREFIX, exc)


def _pump():
    """Main-thread tick: mirror worker state to WM props + the toast."""
    global _pump_registered
    _mirror_to_wm()
    _refresh_toast()
    redraw()
    if _dl.active:
        return _PUMP_INTERVAL_S
    # Terminal tick already ran above — stop self.
    _pump_registered = False
    if _dl.done:
        invalidate_byok_items()
    return None


def _mirror_to_wm() -> None:
    wm = wm_or_none()
    if wm is None:
        return
    for attr, value in (
        ("mixar_local_dl_active", _dl.active),
        ("mixar_local_dl_label", _dl.label),
        ("mixar_local_dl_pct", int(_dl.pct)),
        ("mixar_local_dl_file", _dl.file_label),
        ("mixar_local_last_error", _dl.error),
    ):
        try:
            if getattr(wm, attr, None) != value:
                setattr(wm, attr, value)
        except Exception:
            pass


def toast_store():
    from mixar.modules.common.notifications.store import get_notification_store
    return get_notification_store()


def _refresh_toast() -> None:
    """One sticky toast, one stable id (enqueue_toast discipline)."""
    global _last_toast_key, _toast_suppressed
    try:
        store = toast_store()
        if _dl.active:
            if _dl.file_label == "extract":
                title = "Unpacking local AI runtime…"
            elif _dl.file_label == "local AI runtime":
                title = f"Downloading local AI runtime — {_dl.pct}%"
            else:
                title = f"Downloading {_dl.label} — {_dl.pct}%"
            key = f"active\x1f{title}"
            if key == _last_toast_key:
                return
            # Sticky toast gone after a push == the user closed it.
            if _last_toast_key.startswith("active") and not store.contains(
                LOCAL_MODEL_TOAST_ID
            ):
                _toast_suppressed = True
            _last_toast_key = key
            if not _toast_suppressed:
                store.push(
                    "info", title, body="",
                    ttl_ms=0, id=LOCAL_MODEL_TOAST_ID,
                )
            return
        # Terminal states — exactly one final push/dismiss.
        if not _last_toast_key:
            return
        _last_toast_key = ""
        _toast_suppressed = False
        if _dl.done:
            store.push(
                "success", "Local model ready",
                body=f"{_dl.label} is downloaded on this computer",
                id=LOCAL_MODEL_TOAST_ID,
            )
        elif _dl.error:
            store.push(
                "error", "Local model download failed",
                body=_dl.error, id=LOCAL_MODEL_TOAST_ID,
            )
        else:  # cancelled
            store.dismiss(LOCAL_MODEL_TOAST_ID)
    except Exception as exc:
        logger.debug("%s toast refresh failed: %s", LOG_PREFIX, exc)
