# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parent side: keep a warm worker alive while the agent works.

A fresh worker pays its engines' first use on its first render: Cycles loads
its kernels, EEVEE compiles its pipeline and the scene's material shaders. A
warm worker keeps all of that across file loads, so a render on it is
faster (measured on an M-series Mac: light Cycles final 3.0 s cold, 1.75 s
warm; 3000-object inspection 3.9 s cold, 2.3 s warm; #1955 saw 42.8 s against
5.7 s on a loaded machine).
The supervisor stopped a worker after ``IDLE_TTL_S`` (120 s) without a job,
and an agent often thinks for longer than that between two verification
renders, so most renders of a turn ran on a fresh process.

:func:`note_agent_activity` is called after every agent script the GUI
executor runs. While scripts keep arriving (the last one within
``IDLE_TTL_S``), an idle worker lives up to :data:`ACTIVE_IDLE_TTL_S`; once
the agent stops, the plain ``IDLE_TTL_S`` applies again. A worker drops its
document after every job (``worker_jobs.release_document``), so a warm idle
worker holds its engines, not a second copy of the user's file.

(Starting a worker ahead of the first render, with a warm-up render, was
measured and left out: on a light Cycles scene it saved 0.3 s of a 2.8 s
render, because the cold cost is mostly the scene's own shaders and kernels.)

Main thread only, no ``bpy``.
"""

import time

#: How long an idle worker may live while the agent keeps sending scripts.
ACTIVE_IDLE_TTL_S = 900.0

_activity_at = None    # monotonic time of the last agent script


def note_agent_activity(now=None) -> None:
    """An agent script ran: an idle warm worker may live ``ACTIVE_IDLE_TTL_S``."""
    global _activity_at
    _activity_at = time.monotonic() if now is None else now


def idle_expired(last_used: float, now: float, idle_ttl: float) -> bool:
    """Whether a worker idle since ``last_used`` should stop at ``now``."""
    idle = now - last_used
    if idle <= idle_ttl:
        return False
    agent_active = _activity_at is not None and now - _activity_at <= idle_ttl
    return not (agent_active and idle <= ACTIVE_IDLE_TTL_S)


def reset_for_tests() -> None:
    global _activity_at
    _activity_at = None
