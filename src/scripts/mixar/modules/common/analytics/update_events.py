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


def capture_update_started(version: str, verified: bool, *, context=None) -> None:
    """The helper was spawned and Mixar is quitting to install."""
    capture(
        EVENT_UPDATE_STARTED,
        {"target_version": version, "signature_verified": bool(verified)},
        context=context,
    )


def capture_update_result(
    version: str, outcome: str, stage: str, *, context=None,
) -> None:
    """What the helper reported, read on the next launch.

    ``stage`` is where it stopped (``install``/``verify``/``wait``/...),
    ``outcome`` is ``success``, ``failed`` or ``no_effect`` — the last one
    being "the installer claimed success but the old build started".
    """
    capture(
        EVENT_UPDATE_RESULT,
        {"target_version": version, "outcome": outcome, "stage": stage},
        context=context,
    )
