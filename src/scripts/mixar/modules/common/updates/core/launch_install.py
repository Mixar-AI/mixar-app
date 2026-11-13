# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Installing at Launch: the Fallback for a Session That Never Quit

An update staged in a session that crashed, was force quit or killed
never reached the install on quit. The next launch recognises it from
the staged record (no re-download, no re-hash: size and mtime must still
match what was verified), checks its signature again on a worker thread
— the record is the user's to edit, so it never vouches for one — and,
before the user starts working, shows "Mixar is finishing an update",
quits, and lets the helper install and reopen the new version.

It stands down — and the launch goes on as normal, result report and
update check included — whenever any of these holds:

- the setting is off, or :func:`silent_install.silent_refusal` refuses
  (the signature not verified against this app's Team ID, an
  administrator prompt, another Mixar, background work, failures);
- this launch is restoring a crashed session (its recovery offer is up)
  or was opened with a file — decided again at quit time, when a file
  opened from Finder, a restore, any edit (``bpy.data.is_dirty``) or
  work started meanwhile (any modal tool, a chat message being written,
  a render, an agent script, turn or run, a generation:
  :func:`_session_busy`) cancels it;
- the last attempt's result is still unread (never right after one);
- this version was already tried at launch (``LAUNCH_INSTALL_MAX_ATTEMPTS``,
  counted before the helper starts, so even a crash mid-way counts);
- the download was verified more than ``STAGED_RECORD_MAX_AGE_S`` ago.

It never installs a release the backend no longer offers: this launch
asks the backend itself (after ``updates.check_delay_seconds``, beside the
signature check) and installs only once that check has answered with the
staged installer — the version and its ``sha256``; a failed check, no
update, another version or another installer stands it down. Every update
check that answers also clears a record for this copy naming anything
else — nothing offered, a pulled release, a newer one, a re-published
installer — with its installer (:func:`forget_unoffered`).
"""

import os
import threading
import time

import bpy

from mixar.config.logging_config import get_logger

from ..constants import (
    LAUNCH_INSTALL_MAX_ATTEMPTS,
    LAUNCH_INSTALL_QUIT_DELAY_S,
    STAGED_RECORD_MAX_AGE_S,
    TRIGGER_LAUNCH,
    UPDATE_NOTIFICATION_ID,
)
from . import install_start, installer, staged_record, staging, verify, win_signer
from .preferences import install_on_quit_enabled
from .silent_install import install_refusal, silent_refusal

logger = get_logger(__name__)

# How long after the quit we conclude it is not happening (as Restart &
# Update's watchdog): the helper is killed and the launch goes on.
_QUIT_WATCHDOG_S = 15.0
# The signature check runs codesign twice or thrice (90 s cap each), and
# this launch's update check must answer: past this the launch goes on
# without installing.
_VERIFY_DEADLINE_S = 120.0
_VERIFY_POLL_S = 0.25

_pending = {"request": None, "resume": None, "proc": None, "check": None, "signer": ""}
# Asked once per process: a script reload re-registers the bootstrap
# module, and that is not a launch.
_asked = {"done": False}


def _recovery_offer_pending() -> bool:
    """A crashed session is being offered for restore: leave this launch alone."""
    try:
        from mixar.modules.session_recovery import runtime

        return runtime.current_offer() is not None
    except Exception:  # noqa: BLE001 - unknown means do not interrupt
        return True


def _opened_with_file() -> bool:
    import sys

    return any(arg.lower().endswith((".blend", ".mixar")) for arg in sys.argv[1:])


def launch_install_request():
    """What this launch should install before the user starts, or None.

    Bootstrap ``register()`` time, after the in-progress check and before
    anything reads or purges the staging directory. Cheap: a JSON read, a
    few stats, the eligibility check and one process-table read.
    """
    if _asked["done"]:
        return None
    _asked["done"] = True
    try:
        return _request()
    except Exception:  # noqa: BLE001 - start normally
        logger.error("Could not check for an update to install at launch", exc_info=True)
        return None


def _request():
    if bpy.app.background or not install_on_quit_enabled():
        return None
    if _recovery_offer_pending() or _opened_with_file():
        return None
    from .app_paths import running_target
    from .state import UpdateInfo
    from .update_checker import get_runtime_version, is_newer

    running = get_runtime_version() or ""
    # Staging is per user: only a record naming this copy is ours to judge,
    # and to delete. A copy that cannot tell where it runs judges none.
    target = running_target()
    if not running or not target:
        return None
    for directory in staging.existing_staging_dirs():
        record = staged_record.read(directory)
        if record is None:
            continue
        version = str(record.get("version") or "")
        if record.get("target") != target:
            logger.info("Update %s not installed at launch: staged for another copy", version)
            continue
        if not is_newer(version, running):
            staged_record.remove(directory)  # installed, or older: done with it
            continue
        if os.path.lexists(staging.result_path(directory)):
            logger.info("Update %s not installed at launch: last attempt unread", version)
            return None
        if int(record.get("launch_attempts") or 0) >= LAUNCH_INSTALL_MAX_ATTEMPTS:
            logger.info("Update %s not installed at launch: already tried at launch", version)
            return None
        age = staged_record.age_s(record)
        if age is None or not -60 <= age <= STAGED_RECORD_MAX_AGE_S:
            logger.info("Update %s not installed at launch: downloaded too long ago", version)
            return None
        if not staged_record.intact(record):
            logger.info("Update %s not installed at launch: installer changed", version)
            return None
        info = UpdateInfo(
            latest_version=version, current_version=running,
            download_url=record.get("download_url", ""),
            download_sha256=record.get("sha256", ""),
            installer_type=record.get("installer_type", ""),
        )
        eligibility = installer.check_eligibility(info)
        location = eligibility.location
        if location is not None and record.get("target") != location.target:
            logger.info("Update %s not installed at launch: staged for another copy", version)
            return None
        # The record's verdict only ever refuses here. The signature (and,
        # on Windows, this app's own signer, which nothing has read yet) is
        # judged by the launch's own check before silent_refusal runs.
        refusal = ("" if record.get("verified") and record.get("signer")
                   else "its signature was not verified when it was downloaded")
        refusal = refusal or install_refusal(eligibility, record)
        if refusal:
            logger.info("Update %s not installed at launch: %s", version, refusal)
            return None
        return {"directory": directory, "record": record, "eligibility": eligibility}
    return None


def forget_unoffered(offered) -> None:
    """The update check answered with *offered* (its ``UpdateInfo``; None:
    nothing is offered): drop this copy's staged download unless it is the
    offered installer (:func:`_offer_refusal`).

    Main thread, from the check's callback: a JSON read and two unlinks per
    staging directory. A directory a live helper is installing from is left
    alone, and so is another copy's download (the staging directory is per
    user; that copy's own check decides about it).
    """
    from . import install_marker
    from .app_paths import running_target

    try:
        target = running_target()
        if not target:
            return
        for directory in staging.existing_staging_dirs():
            record = staged_record.read(directory)
            if record is None or record.get("target") != target:
                continue
            offer = _offer(offered)
            refusal = _offer_refusal(offer, record)
            if not refusal or _installer_unknown(offer, record) \
                    or install_marker.guards_staging(directory):
                continue
            logger.info("Forgetting the staged update %s: %s", record.get("version"), refusal)
            staged_record.discard(directory, record)
    except Exception:  # noqa: BLE001 - bookkeeping; the launch re-checks anyway
        logger.warning("Could not forget a staged update", exc_info=True)


def begin_launch_install(request, resume, check_delay=0.0) -> None:
    """Check the installer's signature and ask the backend whether it still
    offers this version, then say "finishing an update" and quit and
    install a moment later.

    *resume* (the normal start-up) runs instead whenever it stands down.
    *check_delay*: seconds before the update check (the API is not running
    yet at bootstrap; ``updates.check_delay_seconds``).
    """
    location = request["eligibility"].location
    check = {"started": time.monotonic(), "verdict": None, "offer": None}
    _pending.update(request=request, resume=resume, proc=None, check=check, signer="")
    _in_background(_verify_worker, check, request["record"].get("installer", ""),
                   location.target if location is not None else "", bpy.app.binary_path)
    bpy.app.timers.register(_check_offer, first_interval=check_delay, persistent=True)
    bpy.app.timers.register(_await_verdict, first_interval=_VERIFY_POLL_S, persistent=True)


def _check_offer():
    """Timer: this launch's own update check. The answer lands in the
    pending check as :func:`_offer` or ``{"error": why}``; like every
    answered check it also forgets a staged download the backend no longer
    offers."""
    check = _pending["check"]
    if check is None:
        return None

    def answered(response):
        try:
            from .update_checker import parse_update_response

            info = parse_update_response(getattr(response, "data", None) or {})
        except Exception as e:  # noqa: BLE001 - an unreadable answer is no answer
            check["offer"] = {"error": f"unreadable answer: {type(e).__name__}"}
            return
        check["offer"] = _offer(info)
        forget_unoffered(info)

    def failed(error):
        check["offer"] = {"error": type(error).__name__}

    try:
        from .trigger import request_update_check

        request_update_check(answered, failed)
    except Exception as e:  # noqa: BLE001 - a check that cannot start has failed
        failed(e)
    return None


def _offer(info) -> dict:
    """An update check's answer (``UpdateInfo`` or None) as judged here."""
    if info is None:
        return {"version": "", "sha256": ""}
    return {"version": info.latest_version, "sha256": info.download_sha256}


def _offer_refusal(offer, record) -> str:
    """Why an update check's *offer* rules out installing *record*'s
    installer. The ``sha256`` names the file (the URL may be presigned
    per check); a release re-published under the same version is
    another installer."""
    from .installer import _same_version

    if "error" in offer:
        return f"this launch's update check failed ({offer['error']})"
    version, offered = str(record.get("version") or ""), offer.get("version") or ""
    if not offered:
        return "the backend no longer offers an update"
    if not _same_version(version, offered):
        return f"the backend now offers {offered}, not {version}"
    if _installer_unknown(offer, record):
        return f"the update check did not say which installer it offers for {version}"
    if offer["sha256"] != str(record.get("sha256") or "").lower():
        return f"the backend no longer offers this installer for {version}"
    return ""


def _installer_unknown(offer, record) -> bool:
    """The record's version is offered with no ``sha256``: the backend sends
    ``download: null`` when it could not presign the installer (no CDN).
    Unknown, not unoffered: the launch stands down, nothing is forgotten."""
    from .installer import _same_version

    return (not offer.get("sha256") and "error" not in offer
            and _same_version(str(record.get("version") or ""), offer.get("version") or ""))


def _in_background(function, *args) -> None:
    threading.Thread(target=function, args=args, name="mixar-launch-install-verify",
                     daemon=True).start()


def _verify_worker(check, installer_path, bundle_path, running_binary) -> None:
    """Worker thread: ``codesign`` / Authenticode on the staged installer
    against the running app — on Windows also this app's own signer
    (:mod:`win_signer`), read before the verdict is published so the gate
    that follows it has the answer. Touches no ``bpy``; the main thread polls."""
    try:
        verdict = verify.verify_installer(
            installer_path, bundle_path=bundle_path, running_binary=running_binary)
        if os.name == "nt" and verdict[0] == verify.VERIFIED:
            win_signer.read(running_binary)
        check["verdict"] = verdict
    except Exception as e:  # noqa: BLE001 - unknown is not verified
        check["verdict"] = (verify.UNVERIFIED, f"verification error: {type(e).__name__}", "")


def _await_verdict():
    """Timer: once the signature check and this launch's update check are
    both in, announce — or stand down as soon as either rules it out, or
    if the user started working meanwhile (they can take two minutes)."""
    check = _pending["check"]
    if check is None:
        return None
    verdict, offer = check["verdict"], check["offer"]
    if verdict is not None:
        result, detail, signer = verdict
        if result != verify.VERIFIED or not signer:
            _stand_down(f"its signature was not verified against this app's ({result}: {detail})")
            return None
    if offer is not None:
        refusal = _offer_refusal(offer, _pending["request"]["record"])
        if refusal:
            _stand_down(refusal)
            return None
    if verdict is None or offer is None:
        if time.monotonic() - check["started"] > _VERIFY_DEADLINE_S:
            _stand_down("the installer's signature check did not finish" if verdict is None
                        else "this launch's update check did not answer")
            return None
        return _VERIFY_POLL_S
    _pending["signer"] = verdict[2]
    reason = _started_working()
    if reason:
        _stand_down(reason)
        return None
    return _announce()


def _announce():
    try:
        from .toasts import push_finishing_update_toast

        push_finishing_update_toast()
    except Exception:  # noqa: BLE001 - the install does not need the toast
        logger.debug("Could not show the finishing-update toast", exc_info=True)
    bpy.app.timers.register(
        _install, first_interval=LAUNCH_INSTALL_QUIT_DELAY_S, persistent=True)
    return None


def _started_working() -> str:
    """Why the user's session must not be quit now, or ``""``."""
    try:
        if bpy.data.filepath:
            return "a file is open"
        if bpy.data.is_dirty:
            return "there are unsaved changes"
    except Exception:  # noqa: BLE001 - unknown means do not quit
        return "the session state is unknown"
    if _recovery_offer_pending():
        return "a crashed session is being restored"
    return _session_busy()


def _session_busy() -> str:
    """Work started during the checks or the toast that a quit would end:
    any modal operator — passive ones too (an asset train and its
    background workers, a snip: session recovery saves under those, but a
    quit ends them) —, a chat message being written (the composer writes
    ``mixie_chat_input`` on every keystroke), then the detectors that
    already watch for work: session recovery's (a render, bake or
    composite, an agent script queued or running, an agent turn or open
    run) and the job queue's (any unfinished generation, queued included)."""
    try:
        from mixar.modules.common.job_queue.core.queue_manager import (
            active_queue_activity,
        )
        from mixar.modules.session_recovery import runtime

        modal = next((op for window in bpy.context.window_manager.windows
                      for op in window.modal_operators), None)
        if modal is not None:
            return f"a tool is running ({getattr(modal, 'bl_idname', '')})"
        if any(str(getattr(scene, "mixie_chat_input", "") or "").strip()
               for scene in bpy.data.scenes):
            return "a chat message is being written"
        if runtime._busy():
            return "a render or agent script is running"
        if runtime.agent_scenes():
            return "an agent is working"
        if active_queue_activity().count:
            return "a generation is running"
    except Exception:  # noqa: BLE001 - unknown means do not quit
        logger.debug("Could not tell whether the session is busy", exc_info=True)
        return "the session state is unknown"
    return ""


def _install():
    try:
        _start_and_quit()
    except Exception:  # noqa: BLE001 - a timer that raises is unregistered
        logger.error("Install at launch failed", exc_info=True)
        _stand_down("it failed to start")
    return None


def _start_and_quit():
    request = _pending["request"]
    record, eligibility = request["record"], request["eligibility"]
    # This process's own verdict, never the record's.
    signer = _pending["signer"]
    reason = _started_working()
    if not reason and not staged_record.intact(record):
        reason = "the installer changed"
    if not reason:
        reason = silent_refusal(eligibility, record, verified=bool(signer), signer=signer)
    if reason:
        _stand_down(reason)
        return
    version = record["version"]
    # Counted before the spawn: whatever happens next, this version is not
    # installed at launch again. A count that could not be written (or one
    # another launch took first) installs nothing: a crash mid-way would
    # otherwise retry at every launch.
    attempts = staged_record.bump(request["directory"], "launch_attempts", version)
    if not 1 <= attempts <= LAUNCH_INSTALL_MAX_ATTEMPTS:
        _stand_down("the attempt could not be recorded")
        return
    try:
        _pending["proc"] = install_start.start_helper(
            installer_path=record["installer"],
            version=version,
            eligibility=eligibility,
            verified=True,
            signer=signer,
            trigger=TRIGGER_LAUNCH,
            relaunch=True,
        )
    except Exception as e:  # noqa: BLE001 - nothing has changed yet
        logger.error("Could not start the update helper at launch: %s", e)
        _stand_down("the updater could not start")
        return
    logger.info("Installing %s at launch: quitting", version)
    bpy.app.timers.register(_quit, first_interval=0.1, persistent=True)
    bpy.app.timers.register(_quit_watchdog, first_interval=_QUIT_WATCHDOG_S, persistent=True)


def _quit():
    try:
        bpy.ops.wm.quit_blender()
    except Exception:  # noqa: BLE001 - recoverable: nothing has been installed
        logger.error("Quit for the launch install failed", exc_info=True)
        _abort()
    return None


def _quit_watchdog():
    if _pending["proc"] is not None:
        logger.error("Mixar is still running %.0fs after the launch-install quit", _QUIT_WATCHDOG_S)
        _abort()
    return None


def _abort():
    proc, _pending["proc"] = _pending["proc"], None
    request = _pending["request"] or {}
    install_start.stop_helper(proc, (request.get("record") or {}).get("installer", ""))
    _stand_down("Mixar did not close")


def _stand_down(reason) -> None:
    """Back to a normal launch: the toast goes, start-up resumes."""
    logger.info("Not installing the update at launch: %s", reason)
    resume = _pending["resume"]
    _pending.update(request=None, resume=None, proc=None, check=None, signer="")
    try:
        from ...notifications.store import get_notification_store

        get_notification_store().dismiss(UPDATE_NOTIFICATION_ID)
    except Exception:  # noqa: BLE001 - the toast is cosmetic
        logger.debug("Could not dismiss the finishing-update toast", exc_info=True)
    if resume is not None:
        resume()


def cancel() -> None:
    """Bootstrap unregister: drop pending timers (not the helper)."""
    for timer in (_check_offer, _await_verdict, _announce, _install, _quit, _quit_watchdog):
        try:
            if bpy.app.timers.is_registered(timer):
                bpy.app.timers.unregister(timer)
        except Exception:  # noqa: BLE001 - shutting down
            pass
