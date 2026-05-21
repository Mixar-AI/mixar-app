# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Polls auth state while any FeatureQueue is paused on AuthenticationError.

Resumes paused jobs (resets them to PENDING and re-pumps) once a token
becomes available again.
"""

import bpy

from mixar.config.logging_config import get_logger

from ..constants import AUTH_RETRY_INTERVAL_S, LOG_PREFIX
from .queue_manager import all_queues

logger = get_logger(__name__)

_running = False


def ensure_auth_watcher() -> None:
    """Register the watcher timer if it isn't already running."""
    global _running
    if _running:
        return
    _running = True
    bpy.app.timers.register(_tick, first_interval=AUTH_RETRY_INTERVAL_S)


def _tick():
    global _running

    paused = [q for q in all_queues() if q.is_auth_paused()]
    if not paused:
        _running = False
        return None

    try:
        from mixar.modules.auth import get_access_token
        token = get_access_token()
    except Exception as e:
        logger.debug("%s auth watcher token check failed: %s", LOG_PREFIX, e)
        return AUTH_RETRY_INTERVAL_S

    if not token:
        return AUTH_RETRY_INTERVAL_S

    logger.info("%s auth recovered, resuming %d queue(s)", LOG_PREFIX, len(paused))
    for q in paused:
        try:
            q.resume_after_auth()
        except Exception as e:
            logger.warning("%s resume failed for %s: %s", LOG_PREFIX, q.feature_key, e)

    _running = False
    return None
