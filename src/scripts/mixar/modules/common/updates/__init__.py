# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar Auto-Update System

Public re-exports for the update checker and state management.  The
update flow is browser-based: the client detects newer versions and
points the user at the downloads page.
"""

from .constants import UPDATE_NOTIFICATION_ID, UpdateState
from .core.state import UpdateInfo, UpdateStateManager, get_update_state
from .core.trigger import trigger_update_check
from .core.update_checker import (
    clear_skipped_version,
    get_current_version,
    get_or_create_install_id,
    get_platform_key,
    get_skipped_version,
    is_newer,
    parse_semver,
    parse_update_response,
    set_skipped_version,
)

__all__ = [
    # Constants / enums
    "UpdateState",
    "UPDATE_NOTIFICATION_ID",
    # State
    "UpdateStateManager",
    "get_update_state",
    "UpdateInfo",
    # Checker helpers
    "parse_semver",
    "is_newer",
    "get_or_create_install_id",
    "get_platform_key",
    "get_current_version",
    "parse_update_response",
    "get_skipped_version",
    "set_skipped_version",
    "clear_skipped_version",
    # Trigger
    "trigger_update_check",
]
