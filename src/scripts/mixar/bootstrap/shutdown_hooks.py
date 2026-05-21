# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Global shutdown hooks.

Several long-lived singletons (HTTP client + connection pool, async
executor + queue processor, WebSocket client, SSE handlers, image
encoder thread pool, toast draw handler) expose ``cleanup_*`` /
``stop_*`` functions that were never wired into the addon teardown
path. On Blender exit / addon reload the daemon threads were torn down
mid-syscall and their captured payloads (requests sessions, urllib3
pools, queued callbacks, websocket frames) leaked.

This bootstrap module calls each cleanup in a defensive ``try``/``except``
block during ``unregister`` and also registers an ``atexit`` mirror so
the hard-exit path still gets a chance to flush.
"""

from __future__ import annotations

import atexit

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_atexit_registered = False


def _safe(label: str, fn, *args, **kwargs) -> None:
    """Run ``fn`` swallowing every exception (shutdown must never raise)."""
    try:
        fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - shutdown path, log and continue
        logger.debug("Shutdown hook %s failed: %s", label, exc)


def _run_all_cleanups() -> None:
    """Invoke every known cleanup_/stop_ entry point in dependency order."""
    # 1. Stop producers first (operator-facing cleanup), then drain consumers.
    try:
        from mixar.modules.space_mixie_chat.core.sse_handler import (
            cleanup_all_sse_handlers,
        )
        _safe("cleanup_all_sse_handlers", cleanup_all_sse_handlers)
    except ImportError:
        pass

    try:
        from mixar.modules.space_mixie_chat.ui.operators.chat_ops import (
            cleanup_image_encoder,
        )
        _safe("cleanup_image_encoder", cleanup_image_encoder)
    except ImportError:
        pass

    try:
        from mixar.modules.common.notifications.toast_timer import (
            cleanup_toast_timer,
        )
        _safe("cleanup_toast_timer", cleanup_toast_timer)
    except ImportError:
        pass

    # 2. Stop the API queue processor + executor (drain in-flight callbacks).
    try:
        from mixar.modules.common.api.processor import stop_api_processor
        _safe("stop_api_processor", stop_api_processor)
    except ImportError:
        pass

    try:
        from mixar.modules.common.api.executor import stop_executor
        _safe("stop_executor", stop_executor, wait=False)
    except ImportError:
        pass

    # 3. Close transport singletons (HTTP session + WebSocket).
    try:
        from mixar.modules.common.api.client import cleanup_http_client
        _safe("cleanup_http_client", cleanup_http_client)
    except ImportError:
        pass

    try:
        from mixar.modules.common.websocket.client import (
            cleanup_websocket_client,
        )
        _safe("cleanup_websocket_client", cleanup_websocket_client)
    except ImportError:
        pass


def register() -> None:
    """Register the atexit fallback so hard-exit paths still flush."""
    global _atexit_registered
    if not _atexit_registered:
        atexit.register(_run_all_cleanups)
        _atexit_registered = True


def unregister() -> None:
    """Normal addon-disable / Blender-quit path: flush every cleanup."""
    _run_all_cleanups()
