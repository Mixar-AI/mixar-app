# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Enqueue-time asset prefetch for heavy texture-apply scripts.

Scripts execute synchronously on Blender's main thread, so any network wait
inside a script freezes the UI (macOS beach ball). For known texture-apply
tools the asset URLs are visible in the script text the moment it arrives on
the WebSocket thread — so we start downloading them THERE, and the executor
timer simply holds the script (UI fully responsive, one cheap flag check per
tick) until the cache is warm. Execution then pays only image decode + node
build, not the network.

The prefetch is best-effort by construction: on failure, timeout, or a URL we
didn't extract, the script's own in-build download path (with its retry and
fail-fast negative cache) takes over exactly as before.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Optional

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Tools whose scripts embed downloadable texture assets. Extend as new heavy
# apply tools appear; anything not listed keeps today's behavior exactly.
PREFETCH_TOOLS = frozenset({"create_layered_material"})

# Never hold a script longer than this waiting for its assets — after the cap
# it executes anyway and the in-script downloads finish the job (partial cache
# hits make even that shorter). Well under the backend's 240s tool timeout.
PREFETCH_WAIT_CAP_SECONDS = 90.0

# Global cap on concurrent asset downloads across ALL queued scripts. A
# parallel texturing wave enqueues 10+ apply scripts in a burst, each with
# 6-8 assets — without a shared cap that's dozens of simultaneous sockets to
# the same S3 host. Plain daemon threads (not a ThreadPoolExecutor) so a hung
# download can never delay Blender's exit.
_DOWNLOAD_SLOTS = threading.BoundedSemaphore(8)

_URL_RE = re.compile(r"https?://[^\s\"'\\)\]}>]+")
_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".exr", ".tif", ".tiff")


def extract_asset_urls(script: str) -> list[str]:
    """Image-asset URLs embedded in a script's text (manifest JSON etc.).

    Filters to image file extensions on the URL path (query strings — e.g.
    S3 presigned params — are ignored for the check but kept in the URL).
    """
    urls: list[str] = []
    for url in _URL_RE.findall(script or ""):
        path = url.split("?", 1)[0].lower()
        if path.endswith(_IMAGE_EXTENSIONS):
            urls.append(url)
    return list(dict.fromkeys(urls))


class ScriptAssetPrefetch:
    """Handle for one script's background asset prefetch.

    ``ready()`` is cheap and main-thread-safe: true once every download has
    finished (success or recorded failure) or the wait cap has passed.
    """

    def __init__(self, urls: list[str]):
        self._done = threading.Event()
        self._deadline = time.monotonic() + PREFETCH_WAIT_CAP_SECONDS
        self.url_count = len(urls)
        thread = threading.Thread(
            target=self._run, args=(urls,), name="mixar-script-prefetch", daemon=True
        )
        thread.start()

    def _run(self, urls: list[str]) -> None:
        started = time.monotonic()
        errors: dict[str, str] = {}
        try:
            # Network + disk only — never bpy — so worker threads are safe.
            from mixar.modules.paint.layered_build.download import download_to_tempfile

            def _fetch(url: str) -> None:
                with _DOWNLOAD_SLOTS:
                    try:
                        download_to_tempfile(url)
                    except Exception as exc:  # noqa: BLE001 — collected below
                        errors[url] = f"{type(exc).__name__}: {exc}"

            workers = [
                threading.Thread(target=_fetch, args=(u,), daemon=True) for u in urls
            ]
            for w in workers:
                w.start()
            for w in workers:
                w.join()
            if errors:
                logger.warning(
                    "script prefetch: %d/%d assets failed (script will retry "
                    "in-build against the negative cache): %s",
                    len(errors), len(urls), "; ".join(list(errors)[:3]),
                )
        except Exception as exc:  # noqa: BLE001 — best-effort by contract
            logger.warning("script prefetch failed (non-fatal): %s", exc)
        finally:
            logger.debug(
                "script prefetch finished: %d url(s) in %.2fs",
                len(urls), time.monotonic() - started,
            )
            self._done.set()

    def ready(self) -> bool:
        return self._done.is_set() or time.monotonic() >= self._deadline


def maybe_start_prefetch(script: str, tool_name: str) -> Optional[ScriptAssetPrefetch]:
    """Start a background asset prefetch for a heavy apply script, or None.

    Called from the WebSocket thread at enqueue time — the whole point is
    that downloads overlap the time the script spends queued, instead of
    blocking the main thread during execution.
    """
    if tool_name not in PREFETCH_TOOLS:
        return None
    urls = extract_asset_urls(script)
    if not urls:
        return None
    logger.info(
        "prefetching %d asset(s) for queued %s script", len(urls), tool_name
    )
    try:
        return ScriptAssetPrefetch(urls)
    except Exception as exc:  # noqa: BLE001 — never block enqueue on prefetch
        logger.warning("could not start script prefetch: %s", exc)
        return None
