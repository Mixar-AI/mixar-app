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
- **``ditto`` does the copying** because it preserves the extended
  attributes and resource forks that the code signature covers; ``cp -R``
  can invalidate the signature and produce "app is damaged".
"""

import os
import shlex
import stat
import subprocess

from mixar.config.logging_config import get_logger

from ..constants import HELPER_LOG_NAME, HELPER_WAIT_FOR_EXIT_S
from .staging import result_path

logger = get_logger(__name__)

_SCRIPT_TEMPLATE = '''#!/bin/sh
# Mixar update helper — generated, safe to delete when not running.
set -u

LOG={log}
INSTALLER={installer}
TARGET={target}
RESULT={result}
PID={pid}
VERSION={version}
EXPECTED_TEAM={team}
REQUIRE_SIGNATURE={require_signature}
WAIT_SECONDS={wait_s}

MOUNT=""
NEW=""
OLD=""

log() {{
    printf '[%s] %s\\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG" 2>&1
}}

record() {{
    printf 'version=%s\\nstage=%s\\nexit=%s\\n' "$VERSION" "$1" "$2" >"$RESULT" 2>/dev/null
}}

cleanup() {{
    if [ -n "$MOUNT" ] && [ -d "$MOUNT" ]; then
        hdiutil detach "$MOUNT" -quiet >>"$LOG" 2>&1 \\
            || hdiutil detach "$MOUNT" -force -quiet >>"$LOG" 2>&1
        rmdir "$MOUNT" 2>/dev/null
    fi
    [ -n "$NEW" ] && [ -d "$NEW" ] && rm -rf "$NEW"
    return 0
}}

relaunch() {{
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

log "update helper started for $VERSION"

# ---- wait for Mixar to exit ------------------------------------------------
waited=0
while kill -0 "$PID" 2>/dev/null; do
    if [ "$waited" -ge "$WAIT_SECONDS" ]; then
        log "Mixar (pid $PID) still running after ${{WAIT_SECONDS}}s - aborting"
        record wait timeout
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
if [ "$REQUIRE_SIGNATURE" = "1" ]; then
    codesign --verify --strict "$SOURCE" >>"$LOG" 2>&1 \\
        || fail verify "downloaded bundle is not validly signed"
    if [ -n "$EXPECTED_TEAM" ]; then
        team=$(codesign -dv --verbose=4 "$SOURCE" 2>&1 \\
            | awk -F= '/^TeamIdentifier=/ {{print $2}}')
        if [ "$team" != "$EXPECTED_TEAM" ]; then
            fail verify "signed by team '$team', expected '$EXPECTED_TEAM'"
        fi
    fi
fi

# ---- swap the bundle -------------------------------------------------------
PARENT=$(dirname "$TARGET")
NEW="$PARENT/.mixar-update-new-$$.app"
OLD="$PARENT/.mixar-update-old-$$.app"
rm -rf "$NEW" "$OLD"

/usr/bin/ditto "$SOURCE" "$NEW" >>"$LOG" 2>&1 || fail copy "could not copy new version"
/usr/bin/xattr -dr com.apple.quarantine "$NEW" >>"$LOG" 2>&1

if [ -d "$TARGET" ]; then
    mv "$TARGET" "$OLD" >>"$LOG" 2>&1 || fail swap "could not move the installed app aside"
fi
if ! mv "$NEW" "$TARGET" >>"$LOG" 2>&1; then
    log "install failed - restoring previous version"
    [ -d "$OLD" ] && mv "$OLD" "$TARGET" >>"$LOG" 2>&1
    # $NEW stays set so cleanup removes the copy we could not install.
    fail swap "could not move the new version into place"
fi
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
):
    """Return the helper shell script text (pure — exercised directly by tests)."""
    return _SCRIPT_TEMPLATE.format(
        log=shlex.quote(os.path.join(staging_dir, HELPER_LOG_NAME)),
        installer=shlex.quote(installer_path),
        target=shlex.quote(target_bundle),
        result=shlex.quote(result_path(staging_dir)),
        pid=int(pid),
        version=shlex.quote(version),
        team=shlex.quote(expected_team or ""),
        require_signature="1" if require_signature else "0",
        wait_s=int(HELPER_WAIT_FOR_EXIT_S),
    )


def launch(
    *,
    installer_path,
    staging_dir,
    target_bundle,
    version,
    expected_team="",
    require_signature=False,
):
    """Write the helper script and start it in its own session.

    ``start_new_session`` detaches the helper from Mixar's process group so
    it survives the quit that is about to follow.

    Returns the helper script path.

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
