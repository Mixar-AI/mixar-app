# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parent-side supervisor for the headless create_model sandbox child process.

The user's GUI Mixar instance owns the sandbox: it launches a second, headless
Mixar process (`--background --python headless_main.py`) on demand, tracks it,
and kills it on shutdown. The backend drives this via the `agent.sandbox_control`
JSON-RPC request, dispatched here through connection_manager's on_sandbox_control
callback.

See: mixar-backend/docs/superpowers/specs/2026-06-04-headless-sandbox-create-model-design.md
"""

import os
import re
import subprocess
import tempfile
import threading

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# connection_id -> subprocess.Popen
_children: dict = {}
# connection_id -> open log file handle (child stdout/stderr)
_child_logs: dict = {}
_lock = threading.Lock()


def _child_log_path(connection_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", connection_id)
    return os.path.join(tempfile.gettempdir(), "mixar_sandbox_{}.log".format(safe))


def _sandbox_popen_kwargs(env: dict, logf) -> dict:
    kwargs = {
        "env": env,
        "stdout": (logf or subprocess.DEVNULL),
        "stderr": subprocess.STDOUT if logf else subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(
            subprocess,
            "CREATE_NEW_PROCESS_GROUP",
            0x00000200,
        )
    else:
        kwargs["start_new_session"] = True
    return kwargs


def _headless_main_path() -> str:
    import mixar.headless as _h
    return os.path.join(os.path.dirname(_h.__file__), "headless_main.py")


def _parent_instance_from(connection_id: str) -> str:
    """Inverse of the backend's ``{parent}-sbx-{n}`` scheme (legacy ``-sbx`` too)."""
    from mixar.modules.common.agent_execution.identity import parent_instance_from
    return parent_instance_from(connection_id)


def _live_children() -> dict:
    """connection_id -> pid for children whose process is still running."""
    return {cid: p.pid for cid, p in _children.items() if p and p.poll() is None}


def _available_ram_bytes() -> int:
    """Best-effort free physical RAM (0 when unknown). Never raises."""
    try:
        if os.name == "nt":
            import ctypes

            class _MEM(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            st = _MEM()
            st.dwLength = ctypes.sizeof(_MEM)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return int(st.ullAvailPhys)
            return 0
        if hasattr(os, "sysconf") and "SC_AVPHYS_PAGES" in os.sysconf_names:
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_AVPHYS_PAGES")
        # macOS: parse vm_stat (free + inactive pages).
        out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5, check=True)
        page = 4096
        pages = 0
        for line in out.stdout.splitlines():
            if "page size of" in line:
                page = int(re.search(r"(\d+) bytes", line).group(1))
            elif line.startswith(("Pages free", "Pages inactive")):
                pages += int(line.split(":")[1].strip().rstrip("."))
        return pages * page
    except Exception:
        return 0


def report_resources() -> dict:
    """Bounded host facts for worker admission (no paths, no secrets)."""
    try:
        from mixar.modules.local_models.core.platform_info import total_ram_bytes
        total = int(total_ram_bytes() or 0)
    except Exception:
        total = 0
    return {
        "success": True,
        "total_ram_mb": total // (1024 * 1024),
        "available_ram_mb": _available_ram_bytes() // (1024 * 1024),
        "cpu_count": os.cpu_count() or 0,
        "workers": len(_live_children()),
        "platform": f"{os.name}",
    }


def spawn_sandbox(connection_id: str, idle_ttl_s: float | None = None,
                  parent_instance_id: str | None = None) -> dict:
    """Launch (or reuse) the headless sandbox child for `connection_id`."""
    with _lock:
        proc = _children.get(connection_id)
        if proc and proc.poll() is None:
            return {"success": True, "pid": proc.pid}  # idempotent — already warm
        # A previous child for this id exited (e.g. idle self-terminate): drop its
        # stale handle + log file before re-spawning.
        if proc is not None:
            _children.pop(connection_id, None)
            old_log = _child_logs.pop(connection_id, None)
            if old_log:
                try:
                    old_log.close()
                except Exception:
                    pass

        from mixar.modules.auth.core.auth import get_access_token
        from mixar.config.config import get_server_url

        parent_iid = parent_instance_id or _parent_instance_from(connection_id)
        env = dict(os.environ)
        env.update({
            "MIXAR_SANDBOX_ACCESS_TOKEN": get_access_token() or "",
            "MIXAR_BACKEND_URL": get_server_url(),
            "MIXAR_SANDBOX_CONNECTION_ID": connection_id,
            "MIXAR_SANDBOX_PARENT_INSTANCE_ID": parent_iid,
            "MIXAR_SANDBOX_PARENT_PID": str(os.getpid()),
        })
        # The PARENT owns the artifact staging area; the worker only writes
        # into the directory it was handed (never sent upstream).
        try:
            from mixar.modules.common.agent_execution.paths import staging_dir
            env["MIXAR_SANDBOX_STAGING_DIR"] = staging_dir(parent_iid)
        except Exception as e:
            logger.warning("no staging dir for worker %s: %s", connection_id, e)
        if idle_ttl_s:
            env["MIXAR_SANDBOX_IDLE_TTL_S"] = str(idle_ttl_s)
        argv = [
            bpy.app.binary_path, "--background", "-noaudio",
            "--python", _headless_main_path(),
        ]
        # Capture the child's stdout/stderr to a log file (NOT DEVNULL) so a
        # child that crashes or fails to connect can actually be diagnosed.
        log_path = _child_log_path(connection_id)
        try:
            logf = open(log_path, "w")
        except Exception:
            logf = None
        try:
            proc = subprocess.Popen(
                argv,
                **_sandbox_popen_kwargs(env, logf),
            )
        except Exception as e:
            logger.error("Failed to spawn sandbox %s: %s", connection_id, e, exc_info=True)
            if logf:
                logf.close()
            return {"success": False, "error": str(e), "pid": None}
        _children[connection_id] = proc
        if logf:
            _child_logs[connection_id] = logf
        logger.info("Sandbox spawned pid=%s id=%s log=%s", proc.pid, connection_id, log_path)
        return {"success": True, "pid": proc.pid}


def _reap_child(proc, cid: str) -> None:
    """Wait for a terminated child; escalate to SIGKILL if it ignores SIGTERM.

    Runs on a daemon thread so shutdown never blocks the main thread, while
    still guaranteeing the child is reaped (no zombie) and cannot survive a
    polite terminate().
    """
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        logger.warning("Sandbox %s ignored terminate; killing pid=%s", cid, proc.pid)
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
    except Exception:
        pass


def shutdown_sandbox(connection_id: str | None = None) -> dict:
    """Terminate one sandbox child (or all if connection_id is None)."""
    with _lock:
        ids = [connection_id] if connection_id else list(_children.keys())
        for cid in ids:
            proc = _children.pop(cid, None)
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
                threading.Thread(
                    target=_reap_child, args=(proc, cid), daemon=True
                ).start()
            logf = _child_logs.pop(cid, None)
            if logf:
                try:
                    logf.close()
                except Exception:
                    pass
        return {"success": True}


def handle_sandbox_control(params: dict) -> dict:
    """Dispatch an agent.sandbox_control request from the backend."""
    action = params.get("action")
    if action == "spawn":
        return spawn_sandbox(
            params["connection_id"], params.get("idle_ttl_s"),
            params.get("parent_instance_id"),
        )
    if action == "shutdown":
        return shutdown_sandbox(params.get("connection_id"))
    if action == "refresh_token":
        # A running child cannot have its environment changed, so credential
        # refresh is a RESTART with the parent's current access token. The
        # backend must only ask this for an IDLE worker (it knows what is in
        # flight; this process does not) — the previous acknowledge-only
        # reply advertised a renewal that never happened.
        cid = params.get("connection_id")
        if not cid:
            return {"success": False, "error": "refresh_token requires connection_id"}
        shutdown_sandbox(cid)
        return spawn_sandbox(cid, params.get("idle_ttl_s"), params.get("parent_instance_id"))
    if action == "report_resources":
        return report_resources()
    return {"success": False, "error": f"unknown sandbox_control action: {action}"}


def kill_all() -> None:
    shutdown_sandbox(None)


def register() -> None:
    """Bootstrap entry point. Nothing to start eagerly — spawning is on demand."""
    logger.debug("sandbox_supervisor ready")


def unregister() -> None:
    """Bootstrap teardown — kill any live sandbox children."""
    kill_all()
