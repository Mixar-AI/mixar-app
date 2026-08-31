# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Update Install Flow

The stateful glue between detection and installation: owns the download
thread, moves :class:`InstallState` along, and turns "Restart & Update"
into a spawned helper plus a quit.

Threading contract — the download runs on a daemon thread that touches
only :mod:`state` (which is lock-guarded) and the filesystem.  Everything
that reads ``bpy`` or the notification store is bounced to the main
thread with ``bpy.app.timers.register``.
"""

import hashlib
import os
import threading

import bpy

from mixar.config.logging_config import get_logger

from ..constants import InstallState
from . import download, installer, staging, verify
from .state import get_update_state

logger = get_logger(__name__)

_lock = threading.Lock()
_thread = None
_cancel = threading.Event()
# The spawned update helper, kept so an aborted quit can kill it.
_helper_proc = None

# How long after scheduling the quit we conclude it is not happening.
# Blender timers stop once real teardown starts, so this only ever fires
# while the event loop is still running normally — i.e. the quit failed or
# something is blocking it — never mid-shutdown on a slow machine.
_QUIT_WATCHDOG_S = 15.0

# Refresh cadence for the "downloading…" toast, in seconds. The download
# thread updates state continuously; the UI only needs to keep up with a
# human reading a percentage.
_PROGRESS_TICK_S = 1.0


# ============================================================================
# Main-thread helpers
# ============================================================================


def _on_main_thread(fn):
    """Run *fn* on the main thread as a one-shot timer."""
    def _once():
        try:
            fn()
        except Exception:  # noqa: BLE001 - a timer that raises is unregistered
            logger.error("Update flow main-thread step failed", exc_info=True)
        return None

    try:
        bpy.app.timers.register(_once, first_interval=0.0)
    except Exception:  # noqa: BLE001 - the app may already be shutting down
        logger.debug("Could not schedule update follow-up (shutting down?)")


def _refresh_ui():
    from .toasts import refresh_update_toast

    refresh_update_toast()


def _redraw_badge():
    from .toasts import tag_topbar_redraw

    tag_topbar_redraw()


def _capture_download_outcome(state):
    """Report staged/failed once the download thread has finished.

    Telemetry runs here, on the main thread, rather than in the worker:
    ``capture()`` reads Blender context for its common properties.
    """
    if state.install_state not in (InstallState.READY, InstallState.FAILED):
        return
    info = state.update_info
    try:
        from ...analytics.update_events import capture_update_download

        capture_update_download(
            info.latest_version if info else "",
            "ready" if state.install_state is InstallState.READY else "failed",
        )
    except Exception:  # noqa: BLE001 - telemetry is fail-open
        logger.debug("Update download telemetry failed", exc_info=True)


def _progress_tick():
    """Repeating timer that keeps the visible percentage moving.

    Only the post-"Restart & Update" toast carries a percentage, so a
    background download re-renders the badge alone. Re-pushing the
    availability toast every second would replace a notification whose
    text has not changed, under a user who may be reaching for it.
    """
    state = get_update_state()
    if state.install_state is not InstallState.DOWNLOADING:
        return None
    if state.install_requested:
        _refresh_ui()
    else:
        _redraw_badge()
    return _PROGRESS_TICK_S


# ============================================================================
# Download
# ============================================================================


def _prepare_staging(version, extension):
    """Resolve the staging directory and the installer path inside it."""
    directory = staging.resolve_staging_dir()
    path = staging.installer_path(directory, version, extension)
    # Keep the file we are about to (re)use; drop every other leftover,
    # including helpers from an attempt that never ran.
    staging.purge_stale(directory, keep_filenames=(os.path.basename(path),))
    return path


def _worker(info, eligibility, running_binary):
    """Download + verify on a daemon thread.

    *running_binary* is captured by the caller: reading ``bpy`` from a
    non-main thread is exactly the kind of thing that works until it
    doesn't.
    """
    state = get_update_state()
    version = info.latest_version
    try:
        path = _prepare_staging(version, eligibility.extension)

        if os.path.isfile(path) and _already_staged(path, info.download_sha256):
            logger.info("Installer for %s already staged — skipping download", version)
        else:
            download.download_installer(
                info.download_url,
                path,
                info.download_sha256,
                on_progress=state.set_download_progress,
                should_cancel=_cancel.is_set,
            )

        verdict, detail = verify.verify_installer(
            path,
            bundle_path=eligibility.location.target if eligibility.location else "",
            running_binary=running_binary,
        )
        if verdict == verify.REJECTED:
            _discard(path)
            raise download.UpdateDownloadError(
                f"Installer rejected: {detail}",
                user_message="Update failed verification",
            )
        if verdict == verify.UNVERIFIED:
            logger.warning("Installer signature not verified: %s", detail)

        state.set_ready(path, verdict == verify.VERIFIED)
        logger.info("Update %s ready to install (%s)", version, verdict)

    except download.UpdateDownloadCancelled:
        logger.info("Update download cancelled by user")
        state.set_install_idle()
    except Exception as e:  # noqa: BLE001 - the thread must never escape
        message = getattr(e, "user_message", "") or "Download failed"
        logger.error("Update download failed: %s", e, exc_info=True)
        state.set_install_failed(message)

    _on_main_thread(_after_download)


def _already_staged(path, expected_sha256):
    """True when *path* is a complete, matching installer from a past run."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest() == (expected_sha256 or "").lower()


def _discard(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _announce_ready(state):
    """Toast once when the installer becomes ready to apply.

    "Downloaded, one restart away" is new and actionable, so it earns an
    interruption even if the availability toast was dismissed — but only
    one, recorded per version.  From then on the badge ("Restart to
    Update") carries it.
    """
    if state.install_state is not InstallState.READY:
        return
    info = state.update_info
    version = info.latest_version if info else ""
    if not version:
        return

    from .toasts import push_update_available_toast
    from .update_checker import (
        ANNOUNCE_READY, get_announced_stage, set_announced_stage,
    )

    if get_announced_stage(version) == ANNOUNCE_READY:
        return
    set_announced_stage(version, ANNOUNCE_READY)
    push_update_available_toast(info)


def _after_download():
    """Main thread: refresh the toast and honour a pending restart request."""
    state = get_update_state()
    _refresh_ui()
    _announce_ready(state)
    _capture_download_outcome(state)

    if state.install_state is InstallState.READY and state.install_requested:
        state.set_install_requested(False)
        # The user asked for this before the download finished. Go through
        # the operator rather than quitting here: it owns the unsaved-work
        # confirmation, and minutes may have passed since they clicked.
        try:
            bpy.ops.mixar.restart_to_update("INVOKE_DEFAULT")
        except Exception:  # noqa: BLE001 - operator may be unavailable
            logger.error("Could not open the restart prompt", exc_info=True)


# ============================================================================
# Public API
# ============================================================================


def start_download(info) -> bool:
    """Begin staging the installer for *info* if we can and haven't yet.

    Returns True when a download thread was started.  Safe to call more
    than once; a second call while one is running is a no-op.
    """
    state = get_update_state()

    eligibility = installer.check_eligibility(info)
    if not eligibility:
        logger.info("Self-install unavailable: %s", eligibility.reason)
        state.set_install_unsupported(eligibility.reason)
        return False

    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return False
        if state.install_state in (InstallState.READY, InstallState.INSTALLING):
            return False

        _cancel.clear()
        state.set_downloading()
        _thread = threading.Thread(
            target=_worker,
            args=(info, eligibility, bpy.app.binary_path),
            name="mixar-update-download",
            daemon=True,
        )
        _thread.start()

    bpy.app.timers.register(_progress_tick, first_interval=_PROGRESS_TICK_S)
    logger.info("Update download started for %s", info.latest_version)
    return True


def cancel_download() -> None:
    """Ask the download thread to stop; state returns to IDLE when it does."""
    _cancel.set()
    get_update_state().set_install_requested(False)


def is_downloading() -> bool:
    return get_update_state().install_state is InstallState.DOWNLOADING


def plan_restart():
    """Decide what a "Restart & Update" click should do right now.

    Returns one of:

    - ``"confirm"`` — the installer is staged; the caller should confirm
      with the user (unsaved work) and then call :func:`apply_and_restart`.
    - ``"waiting"`` — the download is still running and the intent has
      been recorded, so the restart prompt opens by itself when it
      finishes.
    - ``"browser"`` — this install cannot update itself; the caller should
      open the downloads page.

    Keeping the decision here rather than in the operator is what makes it
    testable: under the ``bpy`` mock an operator body is unreachable.
    """
    state = get_update_state()
    install_state = state.install_state

    if install_state is InstallState.READY:
        return "confirm"

    if install_state is InstallState.DOWNLOADING:
        state.set_install_requested(True)
        return "waiting"

    if install_state is InstallState.IDLE and state.update_info is not None:
        # auto_download is off, or a previous attempt was cancelled.
        if start_download(state.update_info):
            state.set_install_requested(True)
            return "waiting"

    return "browser"


def apply_and_restart():
    """Spawn the update helper and quit. Main thread only.

    Returns ``(True, "")`` once the helper is running and the quit is
    scheduled, or ``(False, message)`` when nothing was started — in which
    case the app keeps running untouched.
    """
    state = get_update_state()
    info = state.update_info
    path = state.installer_path

    if state.install_state is not InstallState.READY or not path:
        return False, "The update isn't ready yet"
    if not os.path.isfile(path):
        state.set_install_failed("The downloaded installer is missing")
        return False, "The downloaded installer is missing"

    eligibility = installer.check_eligibility(info)
    if not eligibility:
        state.set_install_unsupported(eligibility.reason)
        return False, eligibility.reason

    global _helper_proc
    try:
        _helper_proc = installer.begin_install(
            installer_path=path,
            staging_dir=os.path.dirname(path),
            version=info.latest_version,
            eligibility=eligibility,
            verified=state.signature_verified,
        )
    except Exception as e:  # noqa: BLE001 - nothing has changed yet
        logger.error("Could not start the update helper: %s", e, exc_info=True)
        state.set_install_failed("Could not start the updater")
        return False, "Could not start the updater"

    state.set_installing()
    try:
        from ...analytics.update_events import capture_update_started

        capture_update_started(info.latest_version, state.signature_verified)
    except Exception:  # noqa: BLE001 - telemetry is fail-open
        logger.debug("Update start telemetry failed", exc_info=True)

    logger.info("Update helper running — quitting to install %s", info.latest_version)
    # Delayed so this operator returns first: the helper is already waiting
    # on our PID and quitting mid-execute leaves Blender tearing down under
    # the caller's feet.
    bpy.app.timers.register(_quit, first_interval=0.1)
    bpy.app.timers.register(_quit_watchdog, first_interval=_QUIT_WATCHDOG_S)
    return True, ""


def _quit():
    try:
        bpy.ops.wm.quit_blender()
    except Exception:  # noqa: BLE001 - recoverable: nothing has been installed
        logger.error("Quit for update failed", exc_info=True)
        _abort_pending_install()
    return None


def _quit_watchdog():
    """Recover when the quit was scheduled but Mixar is still running.

    Without this the failure mode is the worst kind of nothing: the app
    stays open, the toast says "installing", and a helper polls our PID
    for five minutes — and would still install if the user quit later for
    unrelated reasons.
    """
    if get_update_state().install_state is InstallState.INSTALLING:
        logger.error(
            "Mixar is still running %.0fs after the update quit was "
            "scheduled — aborting this install attempt", _QUIT_WATCHDOG_S,
        )
        _abort_pending_install()
    return None


def _abort_pending_install():
    """Kill the waiting helper and return the UI to a retryable READY."""
    global _helper_proc
    proc, _helper_proc = _helper_proc, None
    if proc is not None and proc.poll() is None:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001 - already exited, or access denied
            logger.debug("Could not kill the update helper", exc_info=True)

    state = get_update_state()
    # The staged installer is untouched and still verified — go back to
    # READY so the next click simply tries again.
    if state.installer_path:
        state.set_ready(state.installer_path, state.signature_verified)
    else:
        state.set_install_failed("Mixar didn't close")

    from .toasts import push_install_aborted_toast

    push_install_aborted_toast()


def read_previous_result():
    """Read (and clear) the result the helper left from the last attempt.

    Returns the parsed dict, or ``None``.  Resolving the staging directory
    creates it if missing, which is harmless and means the very first run
    simply finds nothing.
    """
    try:
        directory = staging.resolve_staging_dir()
    except OSError:
        return None
    return installer.consume_result(directory.path)
