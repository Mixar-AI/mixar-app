# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Stop a raw agent script once the backend has stopped waiting for it (#1911).

Agent scripts run on Blender's main thread, so the window is frozen while one
runs ("Not Responding" on Windows). The backend waits a fixed budget for a
raw script (60 s for the orchestrator, DIRECT and MCP, 180 s for workers and
workspaces; ``mixar-backend`` ``scene_core.script_timeout``), counted from
when this client starts it, then reports a timeout and drops any late reply.
The client used to keep running the script: prod, 2026-11, a 60 s check was
still running 4.5 min later and a mesh-hash step 16 min later, each ended
only by the user killing the app.

The stop is cooperative: ``space_mixie_chat/core/sandbox_checkpoints.py``
compiles a check into the model's own code (before each statement, at each
lambda call and comprehension item). At the limit a timer thread sets one
flag; the next check raises :class:`ScriptStop` as if that line had raised,
so every enclosing ``with`` exits through its ``__exit__`` (``temp_override``,
``temp_data``, ``libraries.load``) and every ``finally`` starts. The stop never
lands in Blender, Mixar or backend scaffolding code, which has no checks (the
backend's modifier-cost guard is the run's ``finally``, outside the marked run,
so it always runs whole). A ``finally`` body of the model's own (and the
model's functions it calls) holds the stop for ``HARD_GRACE_S`` more, so
ordinary cleanup completes; past that its next check stops it, as it does a
hold a suspended generator never released. An ``except`` clause is the model's
code like any other: a script that catches the stop is stopped at its next
check. No interpreter hooks: the same on every Python.

Not covered: one long native call (it ends before the next check), and
functions the script registers to run later (``bpy.app.timers.register``,
handlers), which run after the script has returned and are never limited.
"""

from __future__ import annotations

import math
import threading
import time
from types import CodeType
from typing import Any, Optional

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Handshake capability: this client stops a raw script at its deadline, so
# the backend may tell the model a timed-out script is being stopped. Released
# clients take the deadline (exec_envelope_v3) but keep running the script.
CAPABILITY = "script_time_limit_v1"
# Tools whose script is the model's own code. Template tools run first-party
# code with their own bounds and are never limited.
LIMITED_TOOLS = frozenset({"execute_bpy_script", "execute_workspace_script"})
# The backend's budget when the request carries none (a backend before
# ``envelope.deadline``): its longest, BUILD_SCRIPT_TIMEOUT_S.
DEFAULT_BUDGET_S = 180.0
# Ceiling on a budget the backend sends.
MAX_BUDGET_S = 180.0
# The backend gives up only after its liveness probe (5 s timeout, at most two)
# sees the script past its budget; stopping later than that never cuts off a
# script the backend is still waiting for.
GRACE_S = 10.0
# How long past the limit a ``finally`` body may still hold the stop: cleanup
# that loops on, or a hold a never-resumed generator left, ends here.
HARD_GRACE_S = 30.0

# Names the checkpoints read from the script's globals.
HIT_NAME = "_mixar_tl_hit"
STOP_NAME = "_mixar_tl_stop"
HOLD_NAME = "_mixar_tl_hold"
RELEASE_NAME = "_mixar_tl_release"


class ScriptStop(BaseException):
    """BaseException: the script's own ``except Exception`` does not keep it."""


def limit_for(tool_name: str, envelope: Any = None) -> Optional[float]:
    """Seconds a script of ``tool_name`` may run, or None for no limit.

    ``envelope.deadline`` (``ExecutionEnvelope``) is the backend's wait for
    this script in seconds, counted from when the client starts it — relative,
    so the two clocks never need to agree.
    """
    if tool_name not in LIMITED_TOOLS:
        return None
    budget = getattr(envelope, "deadline", None)
    if (not isinstance(budget, (int, float)) or isinstance(budget, bool)
            or not math.isfinite(budget) or budget <= 0):
        budget = DEFAULT_BUDGET_S
    return min(float(budget), MAX_BUDGET_S) + GRACE_S


def _checkpoint_functions(hard_at: float) -> dict:
    """The functions a checkpointed script calls, sharing one hold count.

    ``hard_at`` (``time.monotonic``) is when a hold stops counting.
    """
    held = [0]

    def stop() -> None:
        # Reached only once the limit has passed. A finally body holds the
        # stop until it ends or until hard_at, whichever comes first.
        if not held[0] or time.monotonic() >= hard_at:
            raise ScriptStop()

    def hold() -> None:
        held[0] += 1

    def release() -> None:
        if held[0]:
            held[0] -= 1

    return {STOP_NAME: stop, HOLD_NAME: hold, RELEASE_NAME: release}


def exec_with_time_limit(code: CodeType, namespace: dict, limit_s: Optional[float]) -> None:
    """``exec(code, namespace)``; checkpointed code raises after ``limit_s``.

    A stopped script raises ``TimeoutError`` (an ``Exception``, so the
    executor reports it as the script's error and runs its cleanup). No limit
    runs the script exactly as before.
    """
    if not limit_s:
        exec(code, namespace)  # noqa: S102
        return
    lock = threading.Lock()
    running = [True]
    started = time.monotonic()
    namespace[HIT_NAME] = False
    namespace.update(_checkpoint_functions(started + limit_s + HARD_GRACE_S))

    def _at_limit() -> None:
        with lock:
            if running[0]:
                namespace[HIT_NAME] = True

    timer = threading.Timer(limit_s, _at_limit)
    timer.daemon = True
    timer.start()
    try:
        exec(code, namespace)  # noqa: S102
    except ScriptStop:
        logger.warning("Agent script stopped after %.0fs (limit %.0fs)",
                       time.monotonic() - started, limit_s)
        # Agent-facing (and the step's detail row), so never translated.
        raise TimeoutError(
            f"Script stopped after {limit_s:.0f} s, the longest one script may run: "
            "Mixar cannot respond while a script runs. Changes made before the stop "
            "are kept. Split long work into smaller scripts."
        ) from None
    finally:
        timer.cancel()
        with lock:
            running[0] = False
            # Functions the script left behind (timers, handlers) keep their
            # checks but run unlimited.
            namespace[HIT_NAME] = False
