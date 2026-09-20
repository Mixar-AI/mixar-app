# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Main-thread orchestration over the bpy-free core runtime.

Two halves, one façade:

- **Downloads** live in ``download_flow.py`` (worker thread + 0.5 s pump
  + sticky toast); its public functions are re-exported here so callers
  only ever import ``orchestrator``.
- **Server state** is owned here: ``start_managed(model_id)`` launches
  llama-server through the supervisor; every ``on_state`` callback
  (worker thread) is marshalled to the main thread via
  ``bpy.app.timers.register(first_interval=0.0)`` and handled in
  ``_apply_server_state``: ``retry_fallback`` installs the next runtime
  variant and retries ONCE, ``crashed`` auto-restarts within the
  supervisor's budget (max 2), ``ready`` refreshes the relay's approved
  bases and silently re-registers the BYOK credential when the port
  changed. ``resume_registered()`` (bootstrap, delayed) restores the
  approved relay bases and restarts the managed server when the saved
  BYOK provider is local+managed, so chat works immediately.

House rule reminder: worker threads never touch bpy — every bpy access
below happens inside a timer callback or a function documented as
main-thread-only.
"""

import threading
from typing import Optional

from mixar.config.logging_config import get_logger

from ..constants import LOCAL_MODEL_TOAST_ID, LOG_PREFIX
from . import catalog, manifest, relay, runtime, server_supervisor
from .download_flow import (  # noqa: F401 - re-exported façade
    cancel_download,
    download_in_progress,
    download_snapshot,
    redraw as _redraw,
    start_download,
    toast_store as _toast_store,
    wm_or_none as _wm,
)

logger = get_logger(__name__)

# retry_fallback may only be honoured once per user-initiated start.
_fallback_tried = False

# An explicit Stop must stick: the health watch may not resurrect the
# server until the user (or a login/startup resume) starts it again.
_user_stopped = False


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def is_managed_registration(reg: Optional[dict]) -> bool:
    """True when the manifest's ``registered`` snapshot points at OUR
    managed llama-server (catalog model on 127.0.0.1) rather than a
    user-run custom server."""
    if not isinstance(reg, dict):
        return False
    if catalog.get_model(reg.get("model_id") or "") is None:
        return False
    base = str(reg.get("base_url") or "")
    return base.startswith("http://127.0.0.1:")


def refresh_approved_bases() -> None:
    """Point the relay at every base the backend may legitimately ask for:
    the live managed server (if any) plus the registered snapshot (which
    covers a saved custom server, and the managed base across restarts)."""
    bases = []
    current = server_supervisor.current()
    if current and current.get("port"):
        bases.append(current["base_url"])
    reg = manifest.get_registered()
    if reg and reg.get("base_url") and reg["base_url"] not in bases:
        bases.append(reg["base_url"])
    relay.set_approved_bases(bases)


def _logged_in() -> bool:
    """True when a user session is active. Main thread only."""
    wm = _wm()
    return bool(getattr(wm, "mixie_chat_is_logged_in", False)) if wm else False


# ---------------------------------------------------------------------------
# Managed server orchestration
# ---------------------------------------------------------------------------

def start_managed(model_id: str, *, user_initiated: bool = True) -> bool:
    """Launch (or reuse) the managed llama-server. MAIN THREAD ONLY."""
    global _fallback_tried, _user_stopped
    if user_initiated:
        server_supervisor.reset_restart_count()
    _fallback_tried = False
    _user_stopped = False
    manifest.set_active_model_id(model_id)
    return server_supervisor.start_server(model_id, _on_server_state)


def stop_managed() -> None:
    global _user_stopped
    _user_stopped = True
    server_supervisor.stop_server()
    _set_server_wm("stopped", "")


def _on_server_state(state: str, detail: str) -> None:
    """Supervisor callback — FIRES ON A WORKER THREAD. Marshal only."""
    try:
        import bpy

        def _apply():
            _apply_server_state(state, detail)
            return None

        bpy.app.timers.register(_apply, first_interval=0.0)
    except Exception as exc:
        logger.error("%s could not marshal server state %s: %s",
                     LOG_PREFIX, state, exc)


def _set_server_wm(state: str, model_id: str, error: str = "") -> None:
    wm = _wm()
    if wm is None:
        return
    for attr, value in (
        ("mixar_local_server_state", state),
        ("mixar_local_server_model", model_id),
    ):
        try:
            setattr(wm, attr, value)
        except Exception:
            pass
    if error:
        try:
            wm.mixar_local_last_error = error
        except Exception:
            pass


def _apply_server_state(state: str, detail: str) -> None:
    """Main-thread server-state handler."""
    global _fallback_tried
    current = server_supervisor.current() or {}
    model_id = current.get("model_id") or manifest.get_active_model_id() or ""
    if state in ("spawning", "waiting_health", "ready", "stopped"):
        _set_server_wm(state, model_id)
    if state == "ready":
        refresh_approved_bases()
        _maybe_reregister(detail)
    elif state == "retry_fallback":
        # detail is the NEXT untried variant; the failed one is still in
        # current(). Install the fallback off-thread and retry once.
        failed_variant = current.get("variant") or ""
        if _fallback_tried:
            _set_server_wm("failed", model_id,
                           "The local AI runtime could not start")
        else:
            _fallback_tried = True
            _set_server_wm("waiting_health", model_id)
            threading.Thread(
                target=_fallback_worker,
                args=(model_id, failed_variant),
                daemon=True, name="MixarLocalRuntimeFallback",
            ).start()
    elif state == "crashed":
        if (not server_supervisor.restarts_exhausted()
                and is_managed_registration(manifest.get_registered())):
            logger.warning("%s auto-restarting crashed local server (%d/%d)",
                           LOG_PREFIX, server_supervisor.restart_count(),
                           server_supervisor.MAX_AUTO_RESTARTS)
            _set_server_wm("waiting_health", model_id)
            server_supervisor.start_server(model_id, _on_server_state)
        else:
            _set_server_wm("crashed", model_id,
                           "The local model server stopped unexpectedly")
    elif state == "failed":
        _set_server_wm("failed", model_id, detail or "Local server failed")
    _redraw()


def _fallback_worker(model_id: str, failed_variant: str) -> None:
    """Install the next runtime variant, then retry the server once. NO bpy
    (start_server + the supervisor are thread-safe by design)."""
    try:
        excludes = [failed_variant] if failed_variant else []
        runtime.ensure_runtime(exclude_variants=excludes)
        server_supervisor.start_server(model_id, _on_server_state)
    except Exception as exc:  # noqa: BLE001
        logger.error("%s runtime fallback failed: %s", LOG_PREFIX, exc)
        _on_server_state("failed",
                         getattr(exc, "user_message", "") or str(exc))


def _maybe_reregister(base_url: str) -> None:
    """The managed server came up on a new port — silently re-PUT the BYOK
    credential so the backend relays to the right base. Main thread."""
    reg = manifest.get_registered()
    if not is_managed_registration(reg):
        return
    current = server_supervisor.current() or {}
    if reg.get("model_id") != current.get("model_id"):
        return
    if reg.get("base_url") == base_url:
        return
    model_id = reg["model_id"]
    vision = bool(reg.get("supports_vision"))
    logger.info("%s managed port changed (%s -> %s) — re-registering",
                LOG_PREFIX, reg.get("base_url"), base_url)

    def _on_done(success, _data, err):
        if success:
            manifest.set_registered(base_url, model_id, vision)
            refresh_approved_bases()
        else:
            logger.warning("%s re-register failed: %s", LOG_PREFIX, err)

    try:
        from mixar.modules.byok.core import byok_client
        byok_client.save_credentials(
            provider="local", model=model_id,
            api_key=manifest.get_api_token(),
            base_url=base_url, supports_vision=vision,
            on_done=_on_done,
        )
    except Exception as exc:
        logger.warning("%s re-register unavailable: %s", LOG_PREFIX, exc)


# ---------------------------------------------------------------------------
# Lifecycle (bootstrap / logout / shutdown)
# ---------------------------------------------------------------------------

def resume_registered() -> None:
    """Startup resume (delayed bootstrap timer, MAIN THREAD): restore the
    relay's approved bases; if the saved credential is local+managed and
    the files are still on disk, bring the server up so chat just works.
    Pre-login this only restores bases — the health watch starts the
    server once the user is logged in."""
    refresh_approved_bases()
    reg = manifest.get_registered()
    if not is_managed_registration(reg) or not _logged_in():
        return
    model_id = reg["model_id"]
    if not runtime.model_files_present(model_id):
        logger.warning("%s registered model %s missing on disk — not resuming",
                       LOG_PREFIX, model_id)
        return
    logger.info("%s resuming managed local server (%s)", LOG_PREFIX, model_id)
    start_managed(model_id, user_initiated=True)


def watch_tick() -> None:
    """Light periodic self-heal (bootstrap timer, MAIN THREAD): if the
    registered managed server is not running and the crash budget is not
    exhausted, bring it back. Complements the crash callback (covers
    spawn failures and missed callbacks). Also self-heals the relay's
    approved bases after a logout→login cycle cleared them."""
    if not _logged_in():
        return
    reg = manifest.get_registered()
    if reg and reg.get("base_url") and not relay.get_approved_bases():
        refresh_approved_bases()
    if not is_managed_registration(reg):
        return
    if _user_stopped:
        # The user pressed Stop — respect it until they start it again.
        return
    if server_supervisor.current() is not None:
        return
    if server_supervisor.restarts_exhausted():
        return
    if not runtime.model_files_present(reg["model_id"]):
        return
    logger.info("%s health watch: managed server down — restarting", LOG_PREFIX)
    start_managed(reg["model_id"], user_initiated=False)


def deregister() -> None:
    """The user switched BYOK away from local (or removed BYOK entirely):
    stop the managed server, forget the registration snapshot, and drop
    the relay grants — otherwise startup/login keeps resurrecting a
    llama-server nothing will ever call. Downloaded files stay. MAIN
    THREAD ONLY."""
    cancel_download()
    server_supervisor.stop_all()
    manifest.set_registered(None, None, None)
    relay.set_approved_bases(())
    _set_server_wm("", "")
    try:
        _toast_store().dismiss(LOCAL_MODEL_TOAST_ID)
    except Exception:
        pass


def on_logout() -> None:
    """Logout: stop the server, drop transient UI state and relay grants.
    Downloaded files and the manifest stay (next login resumes)."""
    cancel_download()
    server_supervisor.stop_all()
    relay.set_approved_bases(())
    _set_server_wm("", "")
    try:
        _toast_store().dismiss(LOCAL_MODEL_TOAST_ID)
    except Exception:
        pass


def shutdown() -> None:
    """unregister()/atexit path: kill the server, silence the worker."""
    cancel_download()
    server_supervisor.stop_all()
