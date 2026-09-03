# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar Auto-Update System

Public re-exports for the update checker, its state, and the in-app
installer.  The client detects newer versions, stages and verifies the
release installer in the background, and applies it on a single
"Restart & Update" click; the downloads page remains the fallback for
installs that cannot update themselves.
"""

from .constants import UPDATE_NOTIFICATION_ID, InstallState, UpdateState
from .core.install_flow import (
    apply_and_restart,
    cancel_download,
    is_downloading,
    plan_restart,
    start_download,
)
from .core.installer import check_eligibility
from .core.state import UpdateInfo, UpdateStateManager, get_update_state
from .core.toasts import (
    push_update_available_toast,
    refresh_update_toast,
    report_previous_update_result,
)
from .core.trigger import trigger_update_check
from .core.update_checker import (
    ANNOUNCE_AVAILABLE,
    ANNOUNCE_READY,
    get_announced_stage,
    get_current_version,
    get_or_create_install_id,
    get_platform_key,
    get_runtime_version,
    is_forced,
    is_newer,
    parse_semver,
    parse_update_response,
    set_announced_stage,
)

__all__ = [
    # Constants / enums
    "UpdateState",
    "InstallState",
    "UPDATE_NOTIFICATION_ID",
    # State
    "UpdateStateManager",
    "get_update_state",
    "UpdateInfo",
    # Checker helpers
    "parse_semver",
    "is_newer",
    "is_forced",
    "get_or_create_install_id",
    "get_platform_key",
    "get_current_version",
    "get_runtime_version",
    "parse_update_response",
    "ANNOUNCE_AVAILABLE",
    "ANNOUNCE_READY",
    "get_announced_stage",
    "set_announced_stage",
    # Trigger
    "trigger_update_check",
    # Install flow
    "check_eligibility",
    "start_download",
    "cancel_download",
    "is_downloading",
    "plan_restart",
    "apply_and_restart",
    # Toasts
    "push_update_available_toast",
    "refresh_update_toast",
    "report_previous_update_result",
]
