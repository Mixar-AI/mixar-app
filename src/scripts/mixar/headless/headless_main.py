# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Headless sandbox entry point for create_model sub-builds.

Launched by the parent's sandbox_supervisor:
    Mixar --background --python headless_main.py

Connects the real agent bridge to the backend (token + ids from env), then runs
a MANUAL main-thread pump: in --background, bpy.app.timers do NOT fire, so the
timer-driven main_thread_executor never executes queued scripts. We drain its
queue ourselves on the main thread, execute via the sandboxed ScriptExecutor,
and send the response back over the bridge.

Env:
    MIXAR_SANDBOX_ACCESS_TOKEN, MIXAR_BACKEND_URL, MIXAR_SANDBOX_CONNECTION_ID,
    MIXAR_SANDBOX_PARENT_INSTANCE_ID, MIXAR_SANDBOX_PARENT_PID,
    MIXAR_SANDBOX_PARENT_WATCHDOG_S (optional, default 60)
"""

import os
import queue as _q
import time

from mixar.config.logging_config import get_logger

logger = get_logger("mixar.headless")


def _pid_alive(pid: int) -> bool:
    if not pid:
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _run() -> None:
    token = os.environ.get("MIXAR_SANDBOX_ACCESS_TOKEN", "")
    backend = os.environ.get("MIXAR_BACKEND_URL", "")
    conn_id = os.environ.get("MIXAR_SANDBOX_CONNECTION_ID", "")
    parent_iid = os.environ.get("MIXAR_SANDBOX_PARENT_INSTANCE_ID", "")
    parent_pid = int(os.environ.get("MIXAR_SANDBOX_PARENT_PID", "0") or 0)
    watchdog_s = float(os.environ.get("MIXAR_SANDBOX_PARENT_WATCHDOG_S", "60") or 60)

    from mixar.modules.space_mixie_chat.core import jsonrpc_client as jc
    from mixar.modules.space_mixie_chat.core import main_thread_executor as mte
    from mixar.modules.space_mixie_chat.core.executor import get_executor

    def on_script_execute(script, request_id, tool_name="unknown", session_id=""):
        # Sandbox has no fork "agent session"; queue unconditionally and let the
        # pump below execute + respond. (Production's handler gates on an active
        # session; the sandbox is its own dedicated process so that gate is moot.)
        mte.queue_script_request(script, request_id, tool_name, session_id)
        return None

    client = jc.create_jsonrpc_client(
        host=backend,
        connection_id=conn_id,
        token_getter=lambda: os.environ.get("MIXAR_SANDBOX_ACCESS_TOKEN", token),
        on_script_execute=on_script_execute,
        role="sandbox",
        parent_instance_id=parent_iid,
    )
    client.connect()
    logger.info("headless sandbox %s connecting to %s", conn_id, backend)

    last_connected = time.monotonic()
    while True:
        if not _pid_alive(parent_pid):
            logger.info("parent pid %s gone; exiting", parent_pid)
            break
        if client.is_connected:
            last_connected = time.monotonic()
        elif time.monotonic() - last_connected > watchdog_s:
            logger.info("disconnected > %.0fs; exiting", watchdog_s)
            break

        # MANUAL PUMP — timers do not fire in --background.
        try:
            request_id, script, tool_name, session_id = mte._request_queue.get_nowait()
        except _q.Empty:
            time.sleep(0.05)
            continue

        executor = get_executor()
        try:
            result = executor.execute(script)
            rd = result.to_dict()
        except Exception as e:  # noqa: BLE001
            rd = {"success": False, "error": "{}: {}".format(type(e).__name__, e)}
        if client.is_connected:
            client.queue_response(request_id, rd)

    try:
        client.disconnect()
    except Exception:
        pass


_run()
