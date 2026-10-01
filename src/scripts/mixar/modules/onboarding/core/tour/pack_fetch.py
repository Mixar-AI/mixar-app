# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — background download of a language pack.

``prefetch(code)`` starts (at most) one daemon worker per language:
manifest → ``timing.json`` → parts in order, each through
``common.remote_assets`` (sha256-gated, Range resume, partial kept on
failure so the next launch continues). Picking another language cancels
the previous worker after its current file. ``state(code)`` is a plain
dict the main thread may poll; nothing here touches ``bpy`` except
``packs.cache_root`` (called once, up front, on the calling thread).

The fetch is fire-and-forget: the tour never waits for it (see the
localization plan). A network failure is logged through the network
contract and the state says ``failed``; English plays.
"""

import json
import os
import threading
import urllib.request
from typing import Dict, Optional

from mixar.config.logging_config import get_logger
from mixar.modules.common.remote_assets.core import download as dl

from . import config, language, packs

logger = get_logger(__name__)

_lock = threading.Lock()
_workers: Dict[str, "_Worker"] = {}
_states: Dict[str, dict] = {}


def manifest_url() -> str:
    return os.environ.get(config.ENV_PACKS_MANIFEST_URL) or config.PACKS_MANIFEST_URL


def state(code: str) -> dict:
    code = language.narration_code(code)
    with _lock:
        return dict(_states.get(code) or {"status": "absent"})


def _set(code: str, **fields) -> None:
    with _lock:
        cur = dict(_states.get(code) or {})
        cur.update(fields)
        _states[code] = cur


def _log_failure(exc, context: str) -> None:
    try:
        from mixar.modules.common.network.core.errors import (
            classify_network_error, log_network_failure)
        log_network_failure(logger, classify_network_error(exc), context)
    except Exception:  # noqa: BLE001
        logger.warning("tour pack %s: %s", context, exc)


def fetch_manifest(root: str) -> Optional[dict]:
    """GET the CDN manifest and cache it; on failure fall back to the cached
    copy. Returns the manifest dict or None."""
    url = manifest_url()
    try:
        req = urllib.request.Request(url, headers={"Cache-Control": "max-age=300"})
        with urllib.request.urlopen(req, timeout=config.PACK_MANIFEST_TIMEOUT_S) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("manifest is not an object")
        os.makedirs(root, exist_ok=True)
        tmp = packs.manifest_path(root) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, packs.manifest_path(root))
        return data
    except Exception as exc:  # noqa: BLE001
        _log_failure(exc, "tour pack manifest")
        return packs.read_manifest(root)


class _Worker(threading.Thread):
    def __init__(self, code: str, root: str):
        super().__init__(name=f"tour-pack-{code}", daemon=True)
        self.code, self.root = code, root
        self.cancelled = threading.Event()

    def run(self) -> None:
        code, root = self.code, self.root
        try:
            _set(code, status="downloading", file="manifest", done=0, total=0)
            manifest = fetch_manifest(root)
            entry = packs.manifest_entry(manifest, code)
            if entry is None:
                _set(code, status="failed", reason="no pack in manifest")
                return
            todo = packs.missing_files(root, entry, code)
            total = len(todo)
            policy = dl.Policy(total_deadline_s=config.PACK_PART_DEADLINE_S, what="tour part")
            for i, (url, path, sha) in enumerate(todo):
                if self.cancelled.is_set():
                    _set(code, status="cancelled")
                    return
                if not url or not sha:
                    _set(code, status="failed", reason="manifest entry incomplete")
                    return
                os.makedirs(os.path.dirname(path), exist_ok=True)
                _set(code, status="downloading", file=os.path.basename(path), done=i, total=total)
                dl.download_file(url, path, sha, policy=policy, resume_existing=True,
                                 keep_partial=True, should_cancel=self.cancelled.is_set)
                packs.mark_verified(path, sha)
            _set(code, status="ready", done=total, total=total)
            logger.info("tour pack %s ready (%d files fetched)", code, total)
        except dl.DownloadCancelled:
            _set(code, status="cancelled")
        except dl.DownloadError as exc:
            _set(code, status="failed", reason=exc.user_message)
            logger.warning("tour pack %s: %s", code, exc)
        except Exception as exc:  # noqa: BLE001
            _set(code, status="failed", reason="error")
            _log_failure(exc, f"tour pack {code}")
        finally:
            with _lock:
                if _workers.get(code) is self:
                    _workers.pop(code, None)


def prefetch(code: str) -> bool:
    """Start fetching ``code``'s pack; cancels workers for other languages.
    Returns False when nothing was started (English or subtitles-only,
    already installed, a worker already running, or no cache dir)."""
    code = language.narration_code(code)
    if not code or code == "en":
        _cancel_others(None)
        return False
    root = packs.cache_root(create=True)
    if not root:
        return False
    if packs.installed(code, root) is not None:
        _set(code, status="ready")
        _cancel_others(code)
        return False
    with _lock:
        if code in _workers and _workers[code].is_alive():
            return False
        worker = _Worker(code, root)
        _workers[code] = worker
    _cancel_others(code)
    worker.start()
    return True


def _cancel_others(keep: Optional[str]) -> None:
    with _lock:
        others = [w for c, w in _workers.items() if c != keep]
    for w in others:
        w.cancelled.set()


def shutdown() -> None:
    """Ask every worker to stop (threads are daemons; nothing joins them)."""
    _cancel_others(None)
