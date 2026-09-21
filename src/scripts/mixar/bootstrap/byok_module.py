# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Lifecycle for the agent models catalog cache.

A thin shim, like `bootstrap/local_models_module.py`: all state and transport
live in `modules/byok/core/models_cache.py`, which keeps them beside
`model_suggestions` (their only consumer) and importable without
`mixar.bootstrap`.

What has to happen HERE rather than in the module is the timing. Bootstrap
phase 3 runs before UI auto-discovery (phase 4), so resolving the disk path and
loading the persisted catalog here guarantees the BYOK dropdowns are populated
the first time `byok_props`' EnumProperty callbacks fire — including offline.
Phase 3 is also the only guaranteed once-per-process main-thread point, which is
what keeps `bpy.utils.user_resource` off every worker thread.

The hosted model PREFERENCE hangs off the same cache but has no timer of its
own: it is `no-store` and tiny, so `models_cache` refetches it whenever the
catalog actually changes, and `auth_hooks` refetches it on login. Nothing here
restores it — it is never persisted.
"""

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.byok.core import models_cache, models_storage

logger = get_logger(__name__)

# Matches generation_catalog_cache: late enough not to compete with startup,
# early enough that the first dialog open sees fresh data.
_FIRST_FETCH_DELAY_S = 2.0
# A dashboard change to the enabled provider list reaches a running Blender, and
# — more useful here — this is the retry that recovers "launched offline, network
# came back". Cheap because of the ETag: a 304 does not repopulate anything.
_REVALIDATE_INTERVAL_S = 180.0


def _start_background_fetch():
    models_cache.refresh()
    return None  # Don't repeat


def _periodic_revalidate():
    models_cache.refresh()
    return _REVALIDATE_INTERVAL_S  # Repeat


def register() -> None:
    models_storage.initialize_disk_path()
    models_cache.reset_lifecycle()

    try:
        if models_cache.load_from_disk():
            logger.debug("Agent models catalog restored from disk")
    except Exception as exc:  # noqa: BLE001 — never break bootstrap
        logger.warning("Agent models disk load failed: %s", exc)

    bpy.app.timers.register(_start_background_fetch, first_interval=_FIRST_FETCH_DELAY_S)
    bpy.app.timers.register(_periodic_revalidate, first_interval=_REVALIDATE_INTERVAL_S)


def unregister() -> None:
    models_cache.mark_shutdown()
    for callback in (_start_background_fetch, _periodic_revalidate):
        try:
            if bpy.app.timers.is_registered(callback):
                bpy.app.timers.unregister(callback)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Agent models timer unregister failed: %s", exc)
