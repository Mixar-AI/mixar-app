# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The macOS helper, run for real (``/bin/sh``) on throwaway bundles
(issue 2079 review):

- installing on quit or at launch it swaps nothing while a process still
  runs from the bundle (a ``Mixar -b`` that outlived the quit): it waits,
  bounded, then records ``stage=locked`` with ``locks=``; Restart & Update
  swaps at once, as before; connector pythons never count;
- it never swaps past the life of the update-in-progress marker
  (``stage=expired``);
- a TERM right after the new bundle was moved in is a finished install,
  read from the disk rather than from how far the script got.

The holder is a copy of ``/bin/sleep``, re-signed ad hoc (macOS kills an
unsigned copy of a platform binary), inside the installed bundle.
"""

import re
import shutil
import signal
import subprocess
import time

from update_helper_fixtures import POSIX, exited_pid, fake_codesign, helper_script, result
from update_helper_fixtures import staged_update

import pytest

from mixar.modules.common.updates.constants import (
    HELPER_LOG_NAME,
    HELPER_SWAP_DEADLINE_S,
    HELPER_WAIT_FOR_LOCKS_S,
)


def _holder(path, seconds):
    shutil.copy("/bin/sleep", path)
    signed = subprocess.run(["/usr/bin/codesign", "-f", "-s", "-", str(path)],
                            capture_output=True, timeout=60)
    if signed.returncode != 0:
        pytest.skip("cannot re-sign a copy of sleep")
    return subprocess.Popen([str(path), str(seconds)])


def _helper(tmp_path, holder_name=None, holder_s=30, lock_wait_s=None, **overrides):
    staging, target, archive = staged_update(tmp_path)
    holder = None
    if holder_name:
        holder = _holder(target / "Contents" / "MacOS" / holder_name, holder_s)
        time.sleep(0.3)
    script = helper_script(staging, target, archive, exited_pid(),
                           codesign=fake_codesign(tmp_path), **overrides)
    if lock_wait_s is not None:
        text = script.read_text().replace(
            f"LOCK_WAIT_SECONDS={HELPER_WAIT_FOR_LOCKS_S}", f"LOCK_WAIT_SECONDS={lock_wait_s}")
        script.write_text(text)
    return staging, target, script, holder


def _run(script):
    started = time.monotonic()
    code = subprocess.run(["/bin/sh", str(script)], timeout=120).returncode
    return code, time.monotonic() - started


def _app(target):
    return (target / "Contents" / "MacOS" / "Mixar").read_text()


@POSIX
@pytest.mark.parametrize("trigger", ["quit", "launch"])
def test_a_background_mixar_still_running_from_the_bundle_is_waited_for(tmp_path, trigger):
    staging, target, script, holder = _helper(
        tmp_path, "Mixar Worker", holder_s=3, trigger=trigger, relaunch=False)
    try:
        code, took = _run(script)
    finally:
        holder.kill()
        holder.wait()

    assert (code, _app(target)) == (0, "new")
    assert took >= 2
    assert "waiting for Mixar Worker to exit" in (staging / HELPER_LOG_NAME).read_text()
    assert "locks" not in result(staging)


@POSIX
def test_one_that_outlives_the_wait_is_recorded_as_locked(tmp_path):
    staging, target, script, holder = _helper(tmp_path, "Mixar Worker", lock_wait_s=1)
    try:
        code, _took = _run(script)
    finally:
        holder.kill()
        holder.wait()

    assert (code, _app(target)) == (1, "old")
    outcome = result(staging)
    assert (outcome["stage"], outcome["locks"], outcome["helper_version"]) == (
        "locked", "Mixar Worker", "6")
    assert not list(target.parent.glob(".mixar-update-*"))


@POSIX
@pytest.mark.parametrize("name, trigger", [("python3.13", "quit"), ("Mixar Worker", "click")])
def test_connectors_and_restart_and_update_do_not_wait(tmp_path, name, trigger):
    """A connector python reconnects to the new app; Restart & Update keeps
    swapping at once (relaunch off here only so nothing is opened)."""
    staging, target, script, holder = _helper(tmp_path, name, trigger=trigger, relaunch=False)
    try:
        code, took = _run(script)
    finally:
        holder.kill()
        holder.wait()

    assert (code, _app(target)) == (0, "new")
    assert "waiting for" not in (staging / HELPER_LOG_NAME).read_text()


@POSIX
def test_no_swap_once_the_marker_could_be_stale(tmp_path):
    staging, target, script, _holder_proc = _helper(tmp_path)
    script.write_text(script.read_text().replace(
        f"SWAP_DEADLINE_SECONDS={HELPER_SWAP_DEADLINE_S}", "SWAP_DEADLINE_SECONDS=0"))

    code, _took = _run(script)

    assert (code, _app(target), result(staging)["stage"]) == (1, "old", "expired")
    assert not list(target.parent.glob(".mixar-update-*"))


def test_the_swap_deadline_is_inside_the_marker_s_life():
    from mixar.modules.common.updates.constants import HELPER_MARKER_MAX_AGE_S

    assert 0 < HELPER_SWAP_DEADLINE_S < HELPER_MARKER_MAX_AGE_S


def _interrupt_driver(script_text, **variables):
    """The script's assignments and functions, then *variables* and a call
    to interrupted() — the TERM handler at a chosen moment."""
    start = script_text.index("log() {")
    end = script_text.index("trap interrupted TERM")
    assignments = "\n".join(
        line for line in script_text.splitlines() if re.match(r"^[A-Z_]+=", line))
    chosen = "\n".join(f'{name}="{value}"' for name, value in variables.items())
    return f"#!/bin/sh\nset -u\n{assignments}\n{script_text[start:end]}{chosen}\ninterrupted\n"


@POSIX
@pytest.mark.parametrize("moved_in", [True, False])
def test_a_term_while_the_new_bundle_moves_in_is_judged_from_the_disk(tmp_path, moved_in):
    """MOVING=1, SWAPPED=0: the TERM came between ``mv NEW TARGET`` and
    ``SWAPPED=1`` (moved in: a finished install) or just before that mv
    ran (the old app goes back)."""
    staging, target, archive = staged_update(tmp_path)
    text = helper_script(staging, target, archive, 1).read_text()
    old = target.parent / ".mixar-update-old-1.app"
    new = target.parent / ".mixar-update-new-1.app"
    target.rename(old)
    if moved_in:
        shutil.copytree(old, target)
        (target / "Contents" / "MacOS" / "Mixar").write_text("new")
    else:
        shutil.copytree(old, new)
        (new / "Contents" / "MacOS" / "Mixar").write_text("new")
    driver = staging / "driver.sh"
    driver.write_text(_interrupt_driver(text, OLD=old, NEW=new, MOVING=1, SWAPPED=0))

    assert subprocess.run(["/bin/sh", str(driver)], timeout=30).returncode == 3

    assert _app(target) == ("new" if moved_in else "old")
    assert not old.exists() and not new.exists()
    assert result(staging)["stage"] == ("install" if moved_in else "interrupted")


@POSIX
def test_a_real_term_during_the_lock_wait_touches_nothing(tmp_path):
    staging, target, script, holder = _helper(tmp_path, "Mixar Worker")
    helper = subprocess.Popen(["/bin/sh", str(script)])
    try:
        log = staging / HELPER_LOG_NAME
        deadline = time.monotonic() + 30
        while "waiting for Mixar Worker" not in (log.read_text() if log.exists() else ""):
            assert time.monotonic() < deadline
            time.sleep(0.2)
        helper.send_signal(signal.SIGTERM)
        assert helper.wait(timeout=30) == 3
    finally:
        helper.kill()
        holder.kill()
        holder.wait()

    assert (_app(target), result(staging)["stage"]) == ("old", "interrupted")
    assert not list(target.parent.glob(".mixar-update-*"))
