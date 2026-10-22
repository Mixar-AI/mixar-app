# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Self-update telemetry.

The reason these exist: an update that fails does so after the app has
quit, on a machine we cannot see.  Before this, a Windows install that
never ran looked identical to one that worked — the user simply stayed on
the old version.  These three events make the funnel visible
(staged → started → outcome) without carrying a single piece of user
content: versions, an outcome enum, and a stage.
"""

from .capture import capture
from .constants import (
    EVENT_UPDATE_BLOCKED,
    EVENT_UPDATE_DOWNLOAD,
    EVENT_UPDATE_RESULT,
    EVENT_UPDATE_STARTED,
)


def capture_update_download(version: str, outcome: str, *, context=None) -> None:
    """The installer finished staging (``ready``) or did not (``failed``)."""
    capture(
        EVENT_UPDATE_DOWNLOAD,
        {"target_version": version, "outcome": outcome},
        context=context,
    )


def capture_update_started(
    version: str, verified: bool, *, attempt_id: str = "", context=None,
) -> None:
    """The helper was spawned and Mixar is quitting to install."""
    capture(
        EVENT_UPDATE_STARTED,
        {
            "target_version": version,
            "signature_verified": bool(verified),
            "attempt_id": attempt_id or None,
        },
        context=context,
    )


def capture_update_blocked(version: str, *, context=None) -> None:
    """Mixar was opened while a helper installed *version*, and quit."""
    capture(EVENT_UPDATE_BLOCKED, {"target_version": version}, context=context)


# Diagnostics an install_result may carry beyond version/outcome/stage. A
# fixed list, so nothing the helper writes (paths in particular) can ship
# by accident; every value is a version, an enum, a number or basenames.
RESULT_DETAIL_KEYS = (
    "from_version", "running_version", "exit_code", "msi_error",
    "failure_reason", "attempt_id", "helper_version", "install_kind",
    "installed_version", "relaunch_matched", "relaunch_kind",
    "locking_processes", "wait_s",
)


def capture_update_result(
    version: str, outcome: str, stage: str, *, details=None, context=None,
) -> None:
    """What the helper reported, read on the next launch.

    ``stage`` is where it stopped (``install``/``verify``/``wait``/
    ``locked``/...), ``outcome`` is ``success``, ``pending_reboot``,
    ``failed`` or ``no_effect`` — the last one being "the installer
    claimed success but another build started". *details* holds the
    :data:`RESULT_DETAIL_KEYS`; anything else is dropped.
    """
    properties = {"target_version": version, "outcome": outcome, "stage": stage}
    for key in RESULT_DETAIL_KEYS:
        if key in (details or {}):
            properties[key] = details[key]
    capture(EVENT_UPDATE_RESULT, properties, context=context)
