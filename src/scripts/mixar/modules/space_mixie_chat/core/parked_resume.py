# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Auto-resume of parked builds (P1-6) and the retry-continue sender (P1-5).

Both affordances ride ONE mechanism: the backend's deterministic continuation
path. A plain "continue" message makes classify_node skip re-planning and
re-run only the unfinished lanes (DONE tasks never repeat).

- P1-5: the "Retry failed tasks" chip (backend ``turn_actions``) clicks here.
- P1-6: on transport (re)connect, every idle scene with a saved session asks
  ``POST /agent/parked-turn``; the BACKEND decides whether the last turn is a
  park (dead Blender session, small open tail, no paused question). This
  module only detects, asks, and sends — it never invents a park, never
  answers a question, and never sends twice per app run.
"""

from __future__ import annotations

import threading

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Exact phrase the backend's deterministic continuation guard matches
# (mixar-backend modules/agent/framev2/continuation.py). Never reword.
CONTINUE_MESSAGE = "continue"

# Process-level one-shot guards (a transport flap must not re-ask or re-send).
_checked_sessions: set[str] = set()
_resumed_sessions: set[str] = set()
_lock = threading.Lock()


def claim_check(session_id: str) -> bool:
    """True the first time a session is asked about a park, per app run."""
    with _lock:
        if session_id in _checked_sessions:
            return False
        _checked_sessions.add(session_id)
        return True


def claim_resume(session_id: str) -> bool:
    """True the first time a session may auto-send its resume, per app run."""
    with _lock:
        if session_id in _resumed_sessions:
            return False
        _resumed_sessions.add(session_id)
        return True


def reset_guards() -> None:
    """Forget the one-shot state (logout / tests)."""
    with _lock:
        _checked_sessions.clear()
        _resumed_sessions.clear()


def fetch_parked_report(base_url: str, token: str, session_id: str,
                        timeout: float = 15.0) -> dict | None:
    """Ask the backend about one session. None on ANY failure — a broken
    parked-check must never look like a park (fail toward silence)."""
    import httpx

    from ..constants import AGENT_PARKED_TURN_ENDPOINT

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    try:
        resp = httpx.post(
            f"{base_url}{AGENT_PARKED_TURN_ENDPOINT}",
            json={"session_id": session_id},
            headers=headers,
            timeout=timeout,
        )
    except Exception as exc:
        logger.debug(f"[PARKED] check failed for {session_id[:8]}: {exc}")
        return None
    if resp.status_code != 200:
        logger.debug(
            f"[PARKED] check HTTP {resp.status_code} for {session_id[:8]}"
        )
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("status") != "success":
        return None
    return data


def send_continue(scene) -> bool:
    """Send the bare continuation message through the normal chat send path
    (full guards: state, connection, optimistic UI). IDLE-only by design: a
    retry while a turn is live would race the running build."""
    import bpy

    from ..constants import SessionState
    from .session import get_session_manager

    session = get_session_manager()
    if session.get_state(scene) != SessionState.IDLE:
        return False
    previous = scene.mixie_chat_input
    scene.mixie_chat_input = CONTINUE_MESSAGE
    try:
        result = bpy.ops.mixie_chat.send_message('EXEC_DEFAULT')
    except Exception as exc:
        logger.warning(f"[PARKED] continue send failed: {exc}")
        scene.mixie_chat_input = previous
        return False
    if result != {'FINISHED'}:
        scene.mixie_chat_input = previous
        return False
    return True


def _fire_resume(scene_name: str, open_count: int) -> None:
    """Main-thread: announce, then continue. State re-check catches a turn the
    user started between the ask and the answer."""
    import bpy

    from ..constants import SessionState
    from .session import get_session_manager

    scene = bpy.data.scenes.get(scene_name)
    if scene is None:
        return
    session = get_session_manager()
    if session.get_state(scene) != SessionState.IDLE:
        return
    notice = scene.mixie_chat_messages.add()
    notice.sender = 'AGENT'
    notice.text = (
        "Welcome back — resuming your unfinished build "
        f"({open_count} step{'s' if open_count != 1 else ''} left) from the "
        "last completed step."
    )
    if not send_continue(scene):
        fallback = scene.mixie_chat_messages.add()
        fallback.sender = 'AGENT'
        fallback.text = (
            "Couldn't resume automatically — press Enter on \"continue\" "
            "in the chat to pick the build back up."
        )


def schedule_after_connect(base_url: str) -> None:
    """Transport (re)connected: collect idle sessions on the main thread,
    ask the backend off-thread, auto-resume the first eligible park."""
    import bpy

    from ..constants import SessionState
    from .session import get_session_manager
    from .main_thread_executor import run_on_main_thread

    def _collect():
        try:
            from mixar.modules.auth.core.auth import get_access_token

            token = get_access_token() or ""
            if not token:
                return
            session = get_session_manager()
            candidates = []
            for sc in bpy.data.scenes:
                sid = session.get_session_id(sc)
                if not sid:
                    continue
                if session.get_state(sc) != SessionState.IDLE:
                    continue
                if not claim_check(sid):
                    continue
                candidates.append((sc.name, sid))
            if not candidates:
                return
            threading.Thread(
                target=_ask, args=(base_url, token, candidates),
                daemon=True,
            ).start()
        except Exception as exc:  # never break the connect path
            logger.debug(f"[PARKED] auto-resume skipped: {exc}")

    run_on_main_thread(_collect)


def _ask(base_url: str, token: str,
         candidates: list[tuple[str, str]]) -> None:
    from .main_thread_executor import run_on_main_thread

    for scene_name, sid in candidates:
        report = fetch_parked_report(base_url, token, sid)
        if not report or not report.get("has_parked"):
            continue
        if not report.get("auto_eligible"):
            logger.info(
                f"[PARKED] {sid[:8]} parked tail "
                f"{report.get('open_count')} — left to the user"
            )
            continue
        if not claim_resume(sid):
            continue
        open_count = int(report.get("open_count") or 1)
        logger.info(
            f"[PARKED] auto-resuming {sid[:8]} ({open_count} open task(s))"
        )
        run_on_main_thread(lambda n=scene_name, c=open_count:
                           _fire_resume(n, c))
        return  # one scene, one resume — never two streams from one event
