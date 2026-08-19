# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""llama-server process lifecycle, in the sandbox_supervisor mould.

One managed server at a time: module-global ``_proc`` + lock, idempotent
start (a live child serving the same model is reused), stdout+stderr to a
log file in tempdir, terminate → daemon reaper (wait 5 s → kill → wait
5 s), and a ``stop_all()`` for shutdown hooks (Stage 2 wires it into
``bootstrap/shutdown_hooks._run_all_cleanups`` and ``unregister()``).

THREADING CONTRACT: ``on_state(state, detail)`` callbacks fire FROM A
WORKER THREAD (the health/crash watcher). Callers must marshal to
Blender's main thread themselves (``bpy.app.timers.register(...,
first_interval=0.0)``) and must not touch bpy inside the callback.

States reported:
- ``spawning``        process is being launched
- ``waiting_health``  process is up, polling GET /health
- ``ready``           /health answered 200; detail is the base URL
- ``retry_fallback``  server died before healthy and an untried runtime
                      variant exists; detail is that variant — the
                      orchestrator should ensure_runtime(exclude the
                      failed variant) and call start_server once more
- ``failed``          could not start (no fallback left); detail is why
- ``crashed``         a previously-healthy server exited unexpectedly;
                      restart policy is Stage 2's, capped via
                      restarts_exhausted() (max 2 auto-restarts)
- ``stopped``         explicit stop completed

No bpy imports anywhere in this module.
"""

import os
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

from mixar.config.logging_config import get_logger

from ..constants import (
    DEFAULT_CTX_SIZE,
    HEALTH_TIMEOUT_S,
    LOG_PREFIX,
    PORT_RANGE,
    SERVER_LOG_FILENAME,
)
from . import manifest, runtime

logger = get_logger(__name__)

OnState = Callable[[str, str], None]

MAX_AUTO_RESTARTS = 2

_HEALTH_POLL_INTERVAL_S = 1.0
_HEALTH_REQUEST_TIMEOUT_S = 2.0

_lock = threading.RLock()
_proc: Optional[subprocess.Popen] = None
_logf = None
_generation = 0  # bumped on every start/stop; stale watchers go silent
_healthy = False
_restart_count = 0
_current = {"model_id": None, "port": None, "variant": None, "binary": None,
            "state": "stopped"}


class LocalServerError(Exception):
    """The managed server could not be configured (e.g. no free port)."""


def server_log_path() -> str:
    return os.path.join(tempfile.gettempdir(), SERVER_LOG_FILENAME)


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested directly)
# ---------------------------------------------------------------------------

def build_server_argv(server_bin: str, gguf_path: str, port: int,
                      api_token: str, mmproj_path: Optional[str] = None,
                      ctx_size: int = DEFAULT_CTX_SIZE) -> list:
    """The exact llama-server argv we launch."""
    argv = [
        server_bin,
        "-m", gguf_path,
        "--host", "127.0.0.1",
        "--port", str(port),
        "--no-webui",
        "--api-key", api_token,
        "-ngl", "99",
        "-c", str(ctx_size),
    ]
    if mmproj_path:
        argv += ["--mmproj", mmproj_path]
    return argv


def _port_is_free(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def choose_port(preferred: Optional[int] = None) -> int:
    """*preferred* if it is in range and still free, else a free port from
    PORT_RANGE (bind-tested on 127.0.0.1)."""
    low, high = PORT_RANGE
    if preferred is not None and low <= preferred <= high and _port_is_free(preferred):
        return preferred
    for port in range(low, high + 1):
        if port != preferred and _port_is_free(port):
            return port
    raise LocalServerError(
        f"No free port in {low}-{high} for the local model server"
    )


def _popen_kwargs(logf) -> dict:
    kwargs = {
        "stdout": (logf or subprocess.DEVNULL),
        "stderr": subprocess.STDOUT if logf else subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200,
        )
    else:
        kwargs["start_new_session"] = True
    return kwargs


# ---------------------------------------------------------------------------
# Health / crash watcher (daemon thread)
# ---------------------------------------------------------------------------

def _health_ok(port: int) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/health",
            timeout=_HEALTH_REQUEST_TIMEOUT_S,
        ) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def _watch(proc, gen: int, port: int, variant: str, on_state: OnState) -> None:
    """Poll /health until ready, then watch for an unexpected exit.

    Runs on a daemon thread; every on_state call is from this thread.
    """
    global _healthy, _restart_count
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    while time.monotonic() < deadline:
        with _lock:
            if gen != _generation:
                return  # superseded by a stop/restart
        if proc.poll() is not None:
            _report_startup_death(gen, variant, on_state,
                                  f"server exited with code {proc.returncode}")
            return
        if _health_ok(port):
            with _lock:
                if gen != _generation:
                    return
                _healthy = True
                _current["state"] = "ready"
            on_state("ready", f"http://127.0.0.1:{port}")
            break
        time.sleep(_HEALTH_POLL_INTERVAL_S)
    else:
        try:
            proc.terminate()
        except Exception:
            pass
        _report_startup_death(
            gen, variant, on_state,
            f"no healthy response within {HEALTH_TIMEOUT_S}s",
        )
        return

    # Healthy — now just notice an unexpected death.
    proc.wait()
    with _lock:
        if gen != _generation:
            return  # deliberate stop
        _healthy = False
        _restart_count += 1
        _current["state"] = "crashed"
        count = _restart_count
    logger.warning(
        "%s llama-server exited unexpectedly (code %s, crash #%d, log: %s)",
        LOG_PREFIX, proc.returncode, count, server_log_path(),
    )
    on_state("crashed", f"exit code {proc.returncode}")


def _report_startup_death(gen: int, variant: str, on_state: OnState,
                          reason: str) -> None:
    with _lock:
        if gen != _generation:
            return
        _current["state"] = "failed"
    fallback = runtime.next_fallback_variant(variant) if variant else None
    logger.error(
        "%s llama-server failed to become healthy (%s); log: %s",
        LOG_PREFIX, reason, server_log_path(),
    )
    if fallback:
        on_state("retry_fallback", fallback)
    else:
        on_state("failed", reason)


# ---------------------------------------------------------------------------
# Public lifecycle
# ---------------------------------------------------------------------------

def start_server(model_id: str, on_state: OnState, *,
                 server_bin: Optional[str] = None) -> bool:
    """Launch (or reuse) llama-server for *model_id*. Non-blocking.

    Returns True when a process is running (new or reused); False when
    startup could not even begin (also reported via on_state("failed")).
    The runtime and model files must already be ensured
    (:func:`runtime.ensure_runtime` / :func:`runtime.ensure_model`) — this
    only launches. Readiness arrives via on_state (see module docstring
    for the threading contract).
    """
    global _proc, _logf, _generation, _healthy
    with _lock:
        if (_proc is not None and _proc.poll() is None
                and _current["model_id"] == model_id):
            state = "ready" if _healthy else "waiting_health"
            on_state(state, f"http://127.0.0.1:{_current['port']}")
            return True
        if _proc is not None and _proc.poll() is None:
            _stop_locked()  # switching models: retire the old server first

        variant = None
        binary = server_bin
        if binary is None:
            for spec in runtime.runtime_candidates():
                located = runtime.server_binary_path(spec["variant"])
                if located:
                    binary, variant = located, spec["variant"]
                    break
        if binary is None:
            _current["state"] = "failed"
            on_state("failed", "local AI runtime is not installed")
            return False

        try:
            files = runtime.model_file_paths(model_id)
        except runtime.LocalRuntimeError as exc:
            _current["state"] = "failed"
            on_state("failed", str(exc))
            return False
        if not runtime.model_files_present(model_id):
            _current["state"] = "failed"
            on_state("failed", "model files are not downloaded")
            return False

        try:
            port = choose_port(manifest.get_port())
        except LocalServerError as exc:
            _current["state"] = "failed"
            on_state("failed", str(exc))
            return False
        manifest.set_port(port)
        token = manifest.get_api_token()
        argv = build_server_argv(
            binary, files["gguf"], port, token, mmproj_path=files["mmproj"],
        )
        try:
            logf = open(server_log_path(), "w")
        except Exception:
            logf = None
        _current.update(
            model_id=model_id, port=port, variant=variant, binary=binary,
            state="spawning",
        )
        on_state("spawning", model_id)
        try:
            proc = subprocess.Popen(argv, **_popen_kwargs(logf))
        except Exception as exc:
            logger.error("%s failed to spawn llama-server: %s",
                         LOG_PREFIX, exc, exc_info=True)
            if logf:
                logf.close()
            _current["state"] = "failed"
            on_state("failed", f"could not launch server: {exc}")
            return False
        _proc = proc
        _logf = logf
        _healthy = False
        _generation += 1
        gen = _generation
        _current["state"] = "waiting_health"
    on_state("waiting_health", f"http://127.0.0.1:{port}")
    threading.Thread(
        target=_watch, args=(proc, gen, port, variant, on_state),
        daemon=True, name="mixar-llama-health",
    ).start()
    logger.info("%s llama-server spawned pid=%s port=%s model=%s log=%s",
                LOG_PREFIX, proc.pid, port, model_id, server_log_path())
    return True


def _reap(proc) -> None:
    """Daemon reaper: wait 5 s → kill → wait 5 s (never blocks callers)."""
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        logger.warning("%s llama-server ignored terminate; killing pid=%s",
                       LOG_PREFIX, proc.pid)
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


def _stop_locked() -> None:
    """Terminate the current child. Caller holds ``_lock``."""
    global _proc, _logf, _healthy, _generation
    _generation += 1  # silence the watcher: this exit is deliberate
    proc = _proc
    _proc = None
    _healthy = False
    _current["state"] = "stopped"
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass
        threading.Thread(target=_reap, args=(proc,), daemon=True).start()
    if _logf is not None:
        try:
            _logf.close()
        except Exception:
            pass
        _logf = None


def stop_server() -> None:
    """Terminate the managed server (idempotent, never blocks)."""
    with _lock:
        _stop_locked()


def stop_all() -> None:
    """Shutdown hook: kill everything this module started."""
    stop_server()


def is_healthy() -> bool:
    with _lock:
        return bool(_healthy and _proc is not None and _proc.poll() is None)


def current() -> Optional[dict]:
    """Live server info {model_id, port, pid, state, base_url}, or None."""
    with _lock:
        if _proc is None:
            return None
        return {
            "model_id": _current["model_id"],
            "port": _current["port"],
            "pid": _proc.pid,
            "state": _current["state"],
            "base_url": f"http://127.0.0.1:{_current['port']}",
        }


def restart_count() -> int:
    with _lock:
        return _restart_count


def restarts_exhausted() -> bool:
    """True once the auto-restart budget (2) is used up — Stage 2 should
    stop restarting and surface the failure.

    ``_restart_count`` is incremented when a crash is DETECTED, before the
    orchestrator decides whether to restart — so the Nth restart is decided
    at count == N. Strictly-greater keeps the budget at exactly
    MAX_AUTO_RESTARTS restarts (>= would allow only MAX-1)."""
    with _lock:
        return _restart_count > MAX_AUTO_RESTARTS


def reset_restart_count() -> None:
    """Call after a user-initiated (re)start so the budget starts fresh."""
    global _restart_count
    with _lock:
        _restart_count = 0
