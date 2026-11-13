# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Starting (and Undoing) the Update Helper

The one preparation path every install takes, whatever started it —
Restart & Update (``click``), a normal quit (``quit``) or the launch
after a session that never quit normally (``launch``):

1. forget reopen requests left by an earlier attempt;
2. spawn the helper (:func:`installer.begin_install`);
3. write the update-in-progress marker, so a Mixar opened meanwhile says
   "finishing an update" and quits;
4. when the helper will reopen Mixar, mark the connector ``updating`` so
   an AI app's connector waits for that reopen instead of cold-starting
   the old binary (the reopened app's relay clears it). An install on
   quit reopens nothing, so it leaves the connector alone — the mark
   would hold every connector off for its full 15 minutes;
5. report ``update.install_started`` with the trigger.

:func:`stop_helper` undoes 2-4 when the quit that should follow never
happens. One helper per process, whatever starts it: until then
:func:`start_helper` refuses another (:func:`helper_started`). A second
for the same version would rewrite the first's script while its shell
still reads it, and both would swap the bundle — and the launch
install's quit can find the update READY again (Check for Updates or an
``update`` notification during its wait stages the same version). Main
thread; no ``bpy``.
"""

import os
import uuid

from mixar.config.logging_config import get_logger

from . import install_marker, installer

logger = get_logger(__name__)

# The helper this process started and has not taken back (stop_helper).
_started = {"proc": None}


def helper_started() -> bool:
    """A helper this process started is waiting for it to quit."""
    return _started["proc"] is not None


def start_helper(*, installer_path, version, eligibility, verified, signer,
                 trigger, relaunch):
    """Spawn the helper for the staged *installer_path*; returns its Popen.

    Raises whatever :func:`installer.begin_install` raises, and
    RuntimeError while a helper this process started is waiting — nothing
    has changed then, and the caller must not quit.
    """
    from .update_checker import get_runtime_version

    if helper_started():
        raise RuntimeError("an update helper this process started is already waiting")

    staging_dir = os.path.dirname(installer_path)
    attempt_id = uuid.uuid4().hex
    install_marker.clear_reopen_requests(staging_dir)
    proc = installer.begin_install(
        installer_path=installer_path,
        staging_dir=staging_dir,
        version=version,
        eligibility=eligibility,
        verified=verified,
        signer_thumbprint=signer,
        from_version=get_runtime_version() or "",
        attempt_id=attempt_id,
        relaunch=relaunch,
        trigger=trigger,
    )
    _started["proc"] = proc
    # A Mixar opened mid-install quits instead of running half-replaced
    # files or purging the helper's script; failing to say so never blocks.
    location = getattr(eligibility, "location", None)
    install_marker.write(staging_dir, proc.pid, version, attempt_id,
                         target=getattr(location, "target", "") or "")
    if relaunch:
        _connector_updating(True)
    try:
        from ...analytics.update_events import capture_update_started

        capture_update_started(version, verified, attempt_id=attempt_id, trigger=trigger)
    except Exception:  # noqa: BLE001 - telemetry is fail-open
        logger.debug("Update start telemetry failed", exc_info=True)
    logger.info("Update helper started for %s (trigger %s, relaunch %s)",
                version, trigger, relaunch)
    return proc


def stop_helper(proc, installer_path) -> None:
    """Kill a helper whose quit never came and take back what it implied."""
    _started["proc"] = None
    if proc is not None and proc.poll() is None:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001 - already exited, or access denied
            logger.debug("Could not kill the update helper", exc_info=True)
    _connector_updating(False)  # connectors may cold-start again
    if installer_path:
        install_marker.remove(os.path.dirname(installer_path))


def _connector_updating(updating: bool) -> None:
    try:
        from mixar.modules.mcp_bridge.core import installation as connector_installation

        if updating:
            connector_installation.mark_updating()
        else:
            connector_installation.clear_updating()
    except Exception:  # noqa: BLE001 - the marker is a guard; it expires on its own
        logger.debug("Could not update the connector's updating marker", exc_info=True)
