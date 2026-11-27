# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""The macOS bundle opts out of libmalloc deferred reclamation.

On macOS 26 a failed kernel ring flush inside libmalloc's xzone allocator
aborts the whole process ("BUG IN LIBMALLOC: malloc assertion
err == VM_RECLAIM_SUCCESS failed") from whatever thread happens to free
memory — observed on the render job thread tearing down a Cycles session.
``MallocLargeCache=0`` is read with libmalloc's production getenv and turns
every deferral (tiny, small, large, huge cache) off, so the reclaim ring is
never created. libmalloc reads it once at process start, so it must arrive
through LaunchServices' ``LSEnvironment`` rather than ``os.environ``.
"""

import plistlib
from pathlib import Path


INFO_PLIST = (
    Path(__file__).resolve().parents[1]
    / "src/release/darwin/Mixar.app/Contents/Info.plist"
)


def _info() -> dict:
    return plistlib.loads(INFO_PLIST.read_bytes())


def test_bundle_disables_deferred_reclaim():
    env = _info().get("LSEnvironment")
    assert isinstance(env, dict), "Info.plist must declare LSEnvironment"
    # LaunchServices only passes string values through to the environment.
    assert env.get("MallocLargeCache") == "0"


def test_launch_environment_stays_minimal():
    # Every LSEnvironment key reaches every Mixar process and its children
    # (the headless sandbox, Python subprocesses); widen it deliberately.
    assert set(_info()["LSEnvironment"]) == {"MallocLargeCache"}
