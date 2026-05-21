# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Notification System

Thread-safe notification store with GPU/BLF toast rendering in the
3D viewport. Push notifications from any thread; they are displayed
as auto-dismissing toasts in the top-right corner.

Usage::

    from mixar.modules.common.notifications import get_notification_store

    store = get_notification_store()
    store.push("success", "Done!", body="Model exported successfully")
"""

from .constants import NotificationType
from .rest_api import report_client_version
from .store import NotificationStore, get_notification_store
from .toast_timer import cleanup_toast_timer

__all__ = [
    "NotificationType",
    "NotificationStore",
    "get_notification_store",
    "cleanup_toast_timer",
    "report_client_version",
]
