# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Headless background-worker entry point (harness v3).

Launched by the parent's sandbox_supervisor:
    Mixar --background --python headless_main.py

Connects the real agent bridge to the backend (token + ids from env), then runs
a MANUAL main-thread pump: in --background, bpy.app.timers do NOT fire, so the
timer-driven main_thread_executor never executes queued scripts. We drain its
queue ourselves on the main thread through the SAME take/execute/respond
helpers the GUI pump uses (``mixar.modules.common.agent_execution.pump``), so
the two cannot disagree on the request shape again.

Ownership: a worker has no GUI chat session, so it does not gate on
``has_active_session()``. It validates that each request was assigned to it
(``identity.check_assignment``) and refuses anything else with an error
response on the same request id.

Env:
    MIXAR_SANDBOX_ACCESS_TOKEN, MIXAR_BACKEND_URL, MIXAR_SANDBOX_CONNECTION_ID,
    MIXAR_SANDBOX_PARENT_INSTANCE_ID, MIXAR_SANDBOX_PARENT_PID,
    MIXAR_SANDBOX_PARENT_WATCHDOG_S (optional, default 60),
    MIXAR_SANDBOX_IDLE_TTL_S (optional, 0 = stay until the parent quits)
"""

import os
import time

from mixar.config.logging_config import get_logger

logger = get_logger("mixar.headless")

_PROCESS_STARTED = time.monotonic()
# Bounded wait on an empty queue: the queue itself wakes us, this is only
# the cadence of the parent-pid / disconnect / idle watchdog checks.
_QUEUE_WAIT_S = 0.05
_HOLD_POLL_S = 0.02


def _pid_alive_windows(pid: int) -> bool:
    """Return whether *pid* is alive using Win32 process APIs.

    ``os.kill(pid, 0)`` is a POSIX liveness probe. On Windows it can fail for a
    live process, which made sandbox children exit immediately after launch.
    """
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    process_query_limited_information = 0x1000
    still_active = 259

    kernel32.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
    kernel32.GetExitCodeProcess.restype = ctypes.c_bool
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_bool

    handle = kernel32.OpenProcess(
        process_query_limited_information,
        False,
        int(pid),
    )
    if not handle:
        # If Windows refuses the query, keep running rather than killing a
        # valid sandbox because of an access-policy false negative.
        return ctypes.get_last_error() == 5

    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _pid_alive(pid: int) -> bool:
    if not pid:
        return True
    if os.name == "nt":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def pump_once(q, held, identity, executor, client, mte, pump, check_assignment):
    """Advance the worker pump by one request. Returns ``(held, worked)``.

    Pure function of its collaborators so it is testable without Blender:
    ``mte`` supplies the liveness in-flight markers, ``pump`` the shared
    take/execute/respond helpers.
    """
    req, held, status = pump.take_next(q, held, block_s=_QUEUE_WAIT_S)
    if status == pump.EMPTY:
        return held, False
    if status == pump.HOLDING:
        time.sleep(_HOLD_POLL_S)
        return held, False
    if status in (pump.PREFETCH_FAILED, pump.PREFETCH_EXPIRED):
        pump.respond(client, req, pump.prefetch_refusal(req, status))
        return held, True

    reason = check_assignment(req, identity)
    if reason is not None:
        logger.warning("worker refusing %s (id %s): %s", req.tool_name, req.request_id, reason)
        pump.respond(client, req, {
            "success": False, "error": reason, "error_type": "not_assigned",
        })
        return held, True

    mte._set_inflight(req.tool_name, req.request_id, req.session_id)
    try:
        result = pump.execute_request(req, executor)
    finally:
        mte._clear_inflight()
    logger.info(
        "worker ran %s (id %s) success=%s queue_wait=%sms exec=%sms",
        req.tool_name, req.request_id, result.get("success"),
        req.timing.get("queue_wait_ms"), req.timing.get("exec_ms"),
    )
    pump.respond(client, req, result)
    return held, True


def _run() -> None:
    token = os.environ.get("MIXAR_SANDBOX_ACCESS_TOKEN", "")
    backend = os.environ.get("MIXAR_BACKEND_URL", "")
    parent_pid = int(os.environ.get("MIXAR_SANDBOX_PARENT_PID", "0") or 0)
    watchdog_s = float(os.environ.get("MIXAR_SANDBOX_PARENT_WATCHDOG_S", "60") or 60)
    # Self-terminate after this many seconds with no build, so a finished
    # session's warm worker is reaped. 0 disables (stay until parent quits).
    idle_ttl = float(os.environ.get("MIXAR_SANDBOX_IDLE_TTL_S", "0") or 0)

    from mixar.modules.common.agent_execution import pump
    from mixar.modules.common.agent_execution.identity import (
        check_assignment,
        worker_identity_from_env,
    )
    from mixar.modules.space_mixie_chat.core import jsonrpc_client as jc
    from mixar.modules.space_mixie_chat.core import main_thread_executor as mte
    from mixar.modules.space_mixie_chat.core.executor import get_executor

    identity = worker_identity_from_env()

    def on_script_execute(
        script, request_id, tool_name="unknown", session_id="", agent_ctx=None,
        envelope=None,
    ):
        # No GUI "agent session" here; queue unconditionally and let the pump
        # below validate the assignment, execute and respond.
        mte.queue_script_request(
            script, request_id, tool_name, session_id, agent_ctx, envelope=envelope
        )
        return None

    client = jc.create_jsonrpc_client(
        host=backend,
        connection_id=identity.connection_id,
        token_getter=lambda: os.environ.get("MIXAR_SANDBOX_ACCESS_TOKEN", token),
        on_script_execute=on_script_execute,
        role=identity.role,
        parent_instance_id=identity.parent_instance_id,
    )
    client.connect()
    logger.info(
        "headless worker %s (parent %s) connecting to %s",
        identity.connection_id, identity.parent_instance_id, backend,
    )

    executor = get_executor()
    held = None
    connected_logged = False
    last_connected = time.monotonic()
    last_activity = time.monotonic()
    while True:
        if not _pid_alive(parent_pid):
            logger.info("parent pid %s gone; exiting", parent_pid)
            break
        if client.is_connected:
            last_connected = time.monotonic()
            if not connected_logged:
                connected_logged = True
                logger.info(
                    "worker connected %.2fs after process start",
                    time.monotonic() - _PROCESS_STARTED,
                )
        elif time.monotonic() - last_connected > watchdog_s:
            logger.info("disconnected > %.0fs; exiting", watchdog_s)
            break
        if idle_ttl > 0 and time.monotonic() - last_activity > idle_ttl:
            logger.info("idle > %.0fs with no build; exiting", idle_ttl)
            break

        # MANUAL PUMP — timers do not fire in --background.
        held, worked = pump_once(
            mte._request_queue, held, identity, executor, client, mte, pump,
            check_assignment,
        )
        if worked:
            last_activity = time.monotonic()  # idle window starts after the reply

    try:
        client.disconnect()
    except Exception:
        pass


if __name__ == "__main__":  # `blender --python` runs the file as __main__
    _run()
