# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
macOS Update Helper

Writes and launches the detached shell script that replaces the running
``.app`` bundle with the one inside a staged disk image (or zip), then
reopens it.

Design notes:

- **The bundle is swapped, not overwritten.**  The new bundle is copied
  next to the old one first and the two are exchanged with ``mv``, so a
  copy that fails half way leaves the installed app untouched.  Writing
  into the live bundle would leave an unlaunchable mixture of two
  versions if anything went wrong.
- **The copy lands in the target's own directory.**  ``mv`` is only
  atomic within a volume; staging the copy in ``/tmp`` and moving it into
  ``/Applications`` would degrade to a slow, interruptible copy.
- **The installed path wins over the disk image's name.**  Release DMGs
  have carried version-stamped bundle names, and honouring them would
  leave a second copy behind on every update instead of updating the one
  the user launched.
- **Relaunch happens on every exit path**, including a failed mount or a
  refused signature: the user must never be left with no application.
  An install on quit (``relaunch=False``) is the exception: the user
  closed Mixar, so it stays closed — unless a launch was turned away
  while the helper worked, which left its PID in the reopen requests.
  Those launches are waited for (bounded) before the swap and before the
  reopen: ``open`` would otherwise only bring the quitting one forward.
- **The update-in-progress marker goes right before the relaunch**
  (and on the timeout): until then a Mixar opened by hand quits rather
  than run the old binary over a bundle being swapped.
- **Interrupted means intact.**  A ``TERM`` (logout, shutdown) puts the
  previous bundle back when it was already moved aside, removes the
  half-made copy and records ``stage=interrupted``; ``HUP``/``INT`` are
  ignored. Whether the swap had happened is read from the disk, not from
  how far the script got: once the new bundle is being moved in, its copy
  gone from ``$NEW`` with ``$TARGET`` in place is a finished install
  (``stage=install``). Only a ``SIGKILL`` between the two renames could
  leave no app, and the next run clears the hidden ``.mixar-update-*``
  leftovers.
- **Nothing runs from the bundle when it is swapped** (an install on quit
  or at launch): a background ``Mixar -b`` that outlived the quit, or a
  launch the marker turned away, would otherwise keep running old code
  that lazily loads files from the new bundle. Right before the swap the
  helper waits up to ``HELPER_WAIT_FOR_LOCKS_S`` for every process whose
  executable is inside ``$TARGET`` (``ps -axo comm=``; connector pythons
  aside, as in :mod:`mac_processes`) and otherwise records
  ``stage=locked`` with their names in ``locks=``. Restart & Update keeps
  swapping at once, as before.
- **Never past the marker's life.**  A mount or copy that hangs past
  ``HELPER_SWAP_DEADLINE_S`` (the marker would be stale: a Mixar opened
  then runs) gives up before the swap with ``stage=expired``.
- **The signature pin is the installed app's own Team ID**, read by the
  helper from ``$TARGET`` before anything is replaced: the new bundle must
  be validly signed by that team whenever the app verified the update
  (always, for an install on quit or at launch) or the installed app is
  signed at all. A Team ID it cannot read refuses the install. Only an
  unsigned dev build updated from Restart & Update installs unpinned.
- **``ditto`` does the copying** because it preserves the extended
  attributes and resource forks that the code signature covers; ``cp -R``
  can invalidate the signature and produce "app is damaged".
"""

import os
import posixpath
import shlex
import stat
import subprocess

from mixar.config.logging_config import get_logger

from ..constants import (
    HELPER_LOG_NAME,
    HELPER_MARKER_NAME,
    HELPER_REOPEN_GRACE_S,
    HELPER_REOPEN_NAME,
    HELPER_REOPEN_WAIT_S,
    HELPER_SWAP_DEADLINE_S,
    HELPER_VERSION,
    HELPER_WAIT_FOR_EXIT_S,
    HELPER_WAIT_FOR_LOCKS_S,
    TRIGGER_CLICK,
)
from .staging import result_path

logger = get_logger(__name__)

_SCRIPT_TEMPLATE = '''#!/bin/sh
# Mixar update helper — generated, safe to delete when not running.
set -u

LOG={log}
INSTALLER={installer}
TARGET={target}
RESULT={result}
MARKER={marker}
REOPEN={reopen}
PID={pid}
VERSION={version}
FROM_VERSION={from_version}
ATTEMPT={attempt_id}
TRIGGER={trigger}
EXPECTED_TEAM={team}
REQUIRE_SIGNATURE={require_signature}
RELAUNCH={relaunch}
WAIT_SECONDS={wait_s}
REOPEN_WAIT_SECONDS={reopen_wait_s}
REOPEN_GRACE_SECONDS={reopen_grace_s}
WAIT_FOR_BUNDLE={wait_for_bundle}
LOCK_WAIT_SECONDS={lock_wait_s}
SWAP_DEADLINE_SECONDS={swap_deadline_s}
HELPER_VERSION={helper_version}
CODESIGN=/usr/bin/codesign
STARTED=$(date +%s)

MOUNT=""
UNPACKED=0
NEW=""
OLD=""
LOCKS=""
MOVING=0
SWAPPED=0

log() {{
    printf '[%s] %s\\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG" 2>&1
}}

record() {{
    printf 'version=%s\\nstage=%s\\nexit=%s\\ntrigger=%s\\nfrom_version=%s\\nattempt_id=%s\\nhelper_version=%s\\n' \\
        "$VERSION" "$1" "$2" "$TRIGGER" "$FROM_VERSION" "$ATTEMPT" "$HELPER_VERSION" \\
        >"$RESULT" 2>/dev/null
    [ -n "$LOCKS" ] && printf 'locks=%s\\n' "$LOCKS" >>"$RESULT" 2>/dev/null
    return 0
}}

team_of() {{
    # The Team ID a bundle is signed with; empty when unsigned, ad hoc or unreadable.
    "$CODESIGN" -dv --verbose=4 "$1" 2>&1 \\
        | awk -F= '/^TeamIdentifier=/ {{ if ($2 != "not set") print $2 }}'
}}

cleanup() {{
    if [ -n "$MOUNT" ] && [ -d "$MOUNT" ]; then
        if [ "$UNPACKED" = "1" ]; then
            # Our own expansion of a zip, never a mount point.
            rm -rf "$MOUNT"
        else
            hdiutil detach "$MOUNT" -quiet >>"$LOG" 2>&1 \\
                || hdiutil detach "$MOUNT" -force -quiet >>"$LOG" 2>&1
            rmdir "$MOUNT" 2>/dev/null
        fi
    fi
    [ -n "$NEW" ] && [ -d "$NEW" ] && rm -rf "$NEW"
    return 0
}}

wait_for_turned_away() {{
    # A Mixar the marker turned away is still on its way out: swapping
    # under it, or an `open` that only brings it forward, waits for it.
    [ -s "$REOPEN" ] || return 0
    waited_reopen=0
    for other in $(cat "$REOPEN" 2>/dev/null); do
        case "$other" in ''|*[!0-9]*) continue ;; esac
        kill -0 "$other" 2>/dev/null && log "waiting for turned-away launch $other to exit"
        while kill -0 "$other" 2>/dev/null && [ "$waited_reopen" -lt "$REOPEN_WAIT_SECONDS" ]; do
            sleep 1
            waited_reopen=$((waited_reopen + 1))
        done
        kill -0 "$other" 2>/dev/null && log "turned-away launch $other still running"
    done
    return 0
}}

bundle_holders() {{
    # Comma-joined names of the processes running an executable inside
    # $TARGET (connector pythons aside); empty when none.
    /bin/ps -axo pid=,comm= 2>/dev/null | while read -r hpid hpath; do
        case "$hpath" in
            "$TARGET"/*) ;;
            *) continue ;;
        esac
        hname=$(basename "$hpath")
        case "$hname" in [Pp]ython*) continue ;; esac
        printf '%s\\n' "$hname"
    done | sort -u | paste -sd, -
}}

wait_for_bundle_free() {{
    # Installing on quit or at launch: nothing may run from the bundle
    # when it is swapped (a background `Mixar -b` that outlived the quit).
    [ "$WAIT_FOR_BUNDLE" = "1" ] || return 0
    waited_locks=0
    LOCKS=$(bundle_holders)
    [ -n "$LOCKS" ] && log "waiting for $LOCKS to exit"
    while [ -n "$LOCKS" ]; do
        if [ "$waited_locks" -ge "$LOCK_WAIT_SECONDS" ]; then
            fail locked "still running from $TARGET after ${{LOCK_WAIT_SECONDS}}s: $LOCKS"
        fi
        sleep 1
        waited_locks=$((waited_locks + 1))
        LOCKS=$(bundle_holders)
    done
    return 0
}}

relaunch() {{
    # First: the Mixar about to open must not find the marker naming us.
    rm -f "$MARKER"
    if [ "$RELAUNCH" != "1" ]; then
        # Installed on quit: Mixar stays closed unless a launch was turned
        # away meanwhile. One that read the marker just before it went
        # gets a moment to leave its request.
        sleep "$REOPEN_GRACE_SECONDS"
        if [ ! -s "$REOPEN" ]; then
            rm -f "$REOPEN"
            log "installed on quit - Mixar stays closed"
            return 0
        fi
        log "a launch was turned away during the update - reopening"
    fi
    wait_for_turned_away
    rm -f "$REOPEN"
    if [ -d "$TARGET" ]; then
        log "relaunching $TARGET"
        /usr/bin/open "$TARGET" >>"$LOG" 2>&1
    else
        log "nothing to relaunch at $TARGET"
    fi
}}

fail() {{
    log "FAILED ($1): $2"
    record "$1" 1
    cleanup
    relaunch
    exit 1
}}

interrupted() {{
    # Logout or shutdown: leave a working app, never half of one.
    trap '' TERM
    log "interrupted"
    # Decided from the disk: once the new bundle was being moved in, its
    # copy gone with $TARGET in place is a finished install.
    if [ "$MOVING" = "1" ] && [ ! -e "$NEW" ] && [ -d "$TARGET" ]; then
        SWAPPED=1
    fi
    if [ -n "$OLD" ] && [ -d "$OLD" ]; then
        if [ -d "$TARGET" ]; then
            rm -rf "$OLD"
        elif mv "$OLD" "$TARGET" >>"$LOG" 2>&1; then
            log "restored the previous version"
        fi
    fi
    if [ "$SWAPPED" = "1" ]; then
        record install 0
    else
        record interrupted 1
    fi
    cleanup
    rm -f "$MARKER" "$REOPEN"
    exit 3
}}

trap interrupted TERM
trap '' HUP INT

log "update helper started for $VERSION (trigger $TRIGGER, from $FROM_VERSION)"

# ---- wait for Mixar to exit ------------------------------------------------
waited=0
while kill -0 "$PID" 2>/dev/null; do
    if [ "$waited" -ge "$WAIT_SECONDS" ]; then
        log "Mixar (pid $PID) still running after ${{WAIT_SECONDS}}s - aborting"
        record wait timeout
        rm -f "$MARKER"
        exit 2
    fi
    sleep 1
    waited=$((waited + 1))
done
sleep 1
log "Mixar exited - applying $INSTALLER"

# ---- unpack the installer --------------------------------------------------
case "$INSTALLER" in
    *.zip)
        MOUNT=$(mktemp -d /tmp/mixar-update-XXXXXXXX) || fail unpack "mktemp failed"
        UNPACKED=1
        /usr/bin/ditto -x -k "$INSTALLER" "$MOUNT" >>"$LOG" 2>&1 \\
            || fail unpack "could not expand archive"
        ;;
    *)
        MOUNT=$(mktemp -d /tmp/mixar-update-XXXXXXXX) || fail mount "mktemp failed"
        hdiutil attach "$INSTALLER" -nobrowse -readonly -noautoopen \\
            -mountpoint "$MOUNT" >>"$LOG" 2>&1 \\
            || fail mount "could not mount disk image"
        ;;
esac

SOURCE=$(find "$MOUNT" -maxdepth 2 -name '*.app' -prune -print 2>/dev/null | head -1)
[ -n "$SOURCE" ] || fail unpack "no application bundle inside installer"
log "source bundle: $SOURCE"

# ---- verify before replacing anything --------------------------------------
# The pin is the installed app's own Team ID, read here, not a value handed
# over: required when the app verified the update, and whenever the
# installed app is signed by a team (an unsigned dev build updated from
# Restart & Update is the one case that installs unpinned).
INSTALLED_TEAM=""
[ -d "$TARGET" ] && INSTALLED_TEAM=$(team_of "$TARGET")
if [ "$REQUIRE_SIGNATURE" = "1" ] || [ -n "$INSTALLED_TEAM" ]; then
    [ -n "$INSTALLED_TEAM" ] || fail verify "could not read the installed app's Team ID"
    if [ -n "$EXPECTED_TEAM" ] && [ "$EXPECTED_TEAM" != "$INSTALLED_TEAM" ]; then
        fail verify "installed app signed by team '$INSTALLED_TEAM', expected '$EXPECTED_TEAM'"
    fi
    "$CODESIGN" --verify --strict "$SOURCE" >>"$LOG" 2>&1 \\
        || fail verify "downloaded bundle is not validly signed"
    team=$(team_of "$SOURCE")
    if [ "$team" != "$INSTALLED_TEAM" ]; then
        fail verify "signed by team '$team', expected '$INSTALLED_TEAM'"
    fi
fi

# ---- swap the bundle -------------------------------------------------------
PARENT=$(dirname "$TARGET")
if [ -d "$TARGET" ]; then
    # Leftovers of a helper killed mid-swap (a SIGKILL cannot be trapped).
    for leftover in "$PARENT"/.mixar-update-new-*.app "$PARENT"/.mixar-update-old-*.app; do
        [ -d "$leftover" ] && rm -rf "$leftover"
    done
fi
NEW="$PARENT/.mixar-update-new-$$.app"
OLD="$PARENT/.mixar-update-old-$$.app"
rm -rf "$NEW" "$OLD"

/usr/bin/ditto "$SOURCE" "$NEW" >>"$LOG" 2>&1 || fail copy "could not copy new version"
/usr/bin/xattr -dr com.apple.quarantine "$NEW" >>"$LOG" 2>&1
wait_for_turned_away
wait_for_bundle_free
if [ $(($(date +%s) - STARTED)) -ge "$SWAP_DEADLINE_SECONDS" ]; then
    # The marker is stale by now: a Mixar opened meanwhile was not turned away.
    fail expired "too late to swap the bundle (over ${{SWAP_DEADLINE_SECONDS}}s)"
fi

if [ -d "$TARGET" ]; then
    mv "$TARGET" "$OLD" >>"$LOG" 2>&1 || fail swap "could not move the installed app aside"
fi
MOVING=1
if ! mv "$NEW" "$TARGET" >>"$LOG" 2>&1; then
    MOVING=0
    log "install failed - restoring previous version"
    [ -d "$OLD" ] && mv "$OLD" "$TARGET" >>"$LOG" 2>&1
    # $NEW stays set so cleanup removes the copy we could not install.
    fail swap "could not move the new version into place"
fi
SWAPPED=1
NEW=""
rm -rf "$OLD"

log "updated $TARGET to $VERSION"
record install 0
rm -f "$INSTALLER"
cleanup
relaunch
exit 0
'''


def build_script(
    *,
    installer_path,
    staging_dir,
    target_bundle,
    version,
    pid,
    expected_team="",
    require_signature=False,
    relaunch=True,
    trigger=TRIGGER_CLICK,
    from_version="",
    attempt_id="",
):
    """Return the helper shell script text (pure — exercised directly by tests).

    *relaunch* False is an install on quit: Mixar is reopened only for a
    launch that was turned away while the helper worked.
    """
    # The script is POSIX shell: join the POSIX way even when the text is
    # generated elsewhere (the Windows test run would otherwise embed a
    # backslash).
    return _SCRIPT_TEMPLATE.format(
        log=shlex.quote(os.path.join(staging_dir, HELPER_LOG_NAME)),
        installer=shlex.quote(installer_path),
        target=shlex.quote(target_bundle),
        result=shlex.quote(result_path(staging_dir)),
        marker=shlex.quote(posixpath.join(staging_dir, HELPER_MARKER_NAME)),
        reopen=shlex.quote(posixpath.join(staging_dir, HELPER_REOPEN_NAME)),
        pid=int(pid),
        version=shlex.quote(version),
        from_version=shlex.quote(from_version or ""),
        attempt_id=shlex.quote(attempt_id or ""),
        trigger=shlex.quote(trigger or TRIGGER_CLICK),
        team=shlex.quote(expected_team or ""),
        require_signature="1" if require_signature else "0",
        relaunch="1" if relaunch else "0",
        wait_s=int(HELPER_WAIT_FOR_EXIT_S),
        reopen_wait_s=int(HELPER_REOPEN_WAIT_S),
        reopen_grace_s=int(HELPER_REOPEN_GRACE_S),
        # Restart & Update swaps at once, as it always has.
        wait_for_bundle="0" if (trigger or TRIGGER_CLICK) == TRIGGER_CLICK else "1",
        lock_wait_s=int(HELPER_WAIT_FOR_LOCKS_S),
        swap_deadline_s=int(HELPER_SWAP_DEADLINE_S),
        helper_version=int(HELPER_VERSION),
    )


def launch(
    *,
    installer_path,
    staging_dir,
    target_bundle,
    version,
    expected_team="",
    require_signature=False,
    relaunch=True,
    trigger=TRIGGER_CLICK,
    from_version="",
    attempt_id="",
):
    """Write the helper script and start it in its own session.

    ``start_new_session`` detaches the helper from Mixar's process group so
    it survives the quit that is about to follow.

    Returns the helper's ``subprocess.Popen``.

    Raises:
        OSError: the script could not be written or started — the caller
            must not quit the app.
    """
    script_path = os.path.join(staging_dir, f"mixar-update-{version}.sh")
    script = build_script(
        installer_path=installer_path,
        staging_dir=staging_dir,
        target_bundle=target_bundle,
        version=version,
        pid=os.getpid(),
        expected_team=expected_team,
        require_signature=require_signature,
        relaunch=relaunch,
        trigger=trigger,
        from_version=from_version,
        attempt_id=attempt_id,
    )
    with open(script_path, "w", encoding="utf-8") as handle:
        handle.write(script)
    os.chmod(script_path, stat.S_IRWXU)

    proc = subprocess.Popen(  # noqa: S603 - fixed argv, our own generated script
        ["/bin/sh", script_path],
        cwd=staging_dir,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )
    logger.info("macOS update helper started: %s (pid %s)", script_path, proc.pid)
    return proc
