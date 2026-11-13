# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The macOS helper, run for real (``/bin/sh``), leaves nothing in ``/tmp``
(issue 2079 review): a zip installer is expanded into a
``/tmp/mixar-update-*`` directory of the helper's own, which goes once the
install ends, whether it worked or not. A disk image's mount point is only
ever detached and ``rmdir``-ed, never deleted recursively.
"""

import os
import re
import subprocess

from update_helper_fixtures import POSIX, exited_pid, fake_codesign, helper_script, result
from update_helper_fixtures import staged_update

import pytest

from mixar.modules.common.updates.constants import HELPER_LOG_NAME


def _expansion_dir(staging):
    """This helper's own ``/tmp/mixar-update-*`` directory, named by its
    "source bundle:" log line. Not a before/after listing of ``/tmp``: other
    processes (parallel tests, an older build's helper) create and leave
    such directories meanwhile."""
    log = (staging / HELPER_LOG_NAME).read_text()
    found = re.findall(r"source bundle: (/tmp/mixar-update-\w+)/", log)
    assert len(found) == 1, log
    return found[0]


@POSIX
@pytest.mark.parametrize("new_team, stage", [("TEAM1", "install"), ("OTHER", "verify")])
def test_the_zip_expansion_goes_once_the_helper_ends(tmp_path, new_team, stage):
    staging, target, archive = staged_update(tmp_path, installed_team="TEAM1", new_team=new_team)
    script = helper_script(staging, target, archive, exited_pid(),
                           codesign=fake_codesign(tmp_path), require_signature=True)

    subprocess.run(["/bin/sh", str(script)], timeout=120)

    assert result(staging)["stage"] == stage
    assert not os.path.lexists(_expansion_dir(staging))


def test_a_disk_image_mount_point_is_never_deleted_recursively():
    from mixar.modules.common.updates.core import mac_installer

    script = mac_installer._SCRIPT_TEMPLATE
    cleanup = script[script.index("cleanup() {{"):script.index("wait_for_turned_away() {{")]
    assert cleanup.index('[ "$UNPACKED" = "1" ]') < cleanup.index('rm -rf "$MOUNT"')
    assert cleanup.index("else") < cleanup.index("hdiutil detach") < cleanup.index('rmdir "$MOUNT"')
    dmg = script[script.index("    *)\n        MOUNT="):]
    assert "UNPACKED=1" not in dmg[:dmg.index(";;")]
