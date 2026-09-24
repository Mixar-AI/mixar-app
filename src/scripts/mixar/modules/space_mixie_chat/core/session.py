# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Session state management for Mixie Chat.

Provides a singleton SessionManager that reads/writes session state
from Scene properties. All methods take an explicit scene parameter —
no implicit bpy.context.scene access.
"""

import logging
import threading
import uuid
from typing import Optional

from mixar.config.logging_config import get_logger

from ..constants import (
    STATE_LABELS,
    SessionState,
)

logger = get_logger(__name__)


class SessionManager:
    """
    Stateless accessor for per-scene chat session state.

    All state is stored on Scene properties:
    - scene.mixie_chat_state: Current session state enum
    - scene.mixie_chat_is_busy: Derived busy flag for C++ UI
    - scene.mixie_session_id: Persistent session identifier

    The _active_scenes class set tracks which scene names have active
    sessions (BUSY/MODIFYING/AWAITING_INPUT, or an open run). This is safe
    to read from background threads (CPython GIL protects set membership
    checks).

    Run state lives next to turn state: a backend run spans turns (the
    orchestrator answers "in progress" and ends its turn while workers keep
    building), so a scene whose turn is IDLE can still own an open run —
    ``scene.mixie_run_open`` / ``scene.mixie_run_id``, written only by
    ``set_run`` on the main thread.
    """

    _instance: Optional["SessionManager"] = None
    # Thread-safe tracking of active scenes for background thread checks.
    # Updated only on main thread via set_state()/set_run(). Read from any
    # thread.
    _active_scenes: set = set()
    _active_scenes_lock = threading.Lock()
    # Turn states during which the backend may address scripts to the scene.
    _ACTIVE_TURN_STATES = frozenset(
        {SessionState.BUSY, SessionState.MODIFYING, SessionState.AWAITING_INPUT}
    )

    def __new__(cls) -> "SessionManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    # ========================================================================
    # State Access (scene-explicit)
    # ========================================================================

    @staticmethod
    def get_state(scene) -> SessionState:
        """Get session state from a scene.

        Args:
            scene: bpy.types.Scene instance

        Returns:
            SessionState enum value
        """
        if not scene or not hasattr(scene, 'mixie_chat_state'):
            return SessionState.OFFLINE
        state_str = scene.mixie_chat_state
        try:
            return SessionState(state_str.lower())
        except (ValueError, AttributeError):
            return SessionState.OFFLINE

    @staticmethod
    def set_state(scene, state: SessionState) -> None:
        """Set session state on a scene. Must be called from the main thread.

        Also syncs:
        - scene.mixie_chat_is_busy (for C++ UI)
        - _active_scenes set (for thread-safe background checks)

        Args:
            scene: bpy.types.Scene instance
            state: New SessionState
        """
        if not scene or not hasattr(scene, 'mixie_chat_state'):
            logger.warning("Cannot set state: scene missing mixie_chat_state property")
            return

        old_str = scene.mixie_chat_state
        new_str = state.value.upper()

        if old_str != new_str or state != SessionState.BUSY:
            from .cat_activity import reset_for_state
            reset_for_state(scene, new_str)

        if old_str == new_str:
            return

        scene.mixie_chat_state = new_str

        # Sync derived is_busy flag for C++ rendering code
        if hasattr(scene, 'mixie_chat_is_busy'):
            scene.mixie_chat_is_busy = (state == SessionState.BUSY)

        active_states = SessionManager._ACTIVE_TURN_STATES
        is_active = state in active_states
        was_active = old_str in {s.value.upper() for s in active_states}

        # Stamp the chat mode the running turn started in. The agent
        # viewport lock (halo + input block) reads this instead of the
        # live mixie_chat_mode dropdown, which stays editable mid-turn —
        # flipping it (AGENT → ASK → AGENT) must not lift the lock out
        # from under a running agent turn, nor raise it for a running
        # Ask turn. Stamped on the inactive→active edge, held across
        # intra-turn transitions (BUSY ↔ AWAITING_INPUT ↔ MODIFYING),
        # cleared when the turn ends.
        if hasattr(scene, 'mixie_chat_active_turn_mode'):
            if is_active and not was_active:
                scene.mixie_chat_active_turn_mode = (
                    getattr(scene, 'mixie_chat_mode', '') or ''
                )
            elif not is_active:
                scene.mixie_chat_active_turn_mode = ''

        # A new RUN starts with an empty Parallel Agents panel: the previous
        # run's cards stay up after it ends (so its outcome is readable) and
        # a turn that never fans out would otherwise leave them there. A
        # wake-up turn of an open run keeps the cards — its workers are the
        # ones on them.
        if is_active and not was_active and not SessionManager.run_open(scene):
            try:
                from mixar.modules.agent_panel.core.cards import clear_cards
                clear_cards()
            except Exception:  # noqa: BLE001 — the panel never blocks a turn
                pass

        SessionManager._sync_active_scene(scene, is_active)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"STATE CHANGE [{scene.name}]: {old_str} -> {new_str}")

    @staticmethod
    def _sync_active_scene(scene, turn_active: bool) -> None:
        """Keep ``_active_scenes`` = scenes with an active turn OR an open run.

        Background worker scripts of an open run arrive while the
        orchestrator is idle; counting the run here is what lets
        ``has_active_session`` accept them instead of refusing with
        "Agent session not active".
        """
        active = turn_active or SessionManager.run_open(scene)
        with SessionManager._active_scenes_lock:
            if active:
                SessionManager._active_scenes.add(scene.name)
            else:
                SessionManager._active_scenes.discard(scene.name)

    # ========================================================================
    # Run state (a backend run spans turns)
    # ========================================================================

    @staticmethod
    def run_open(scene) -> bool:
        """True while the scene's backend run is open (workers may still build)."""
        # `is True`: a BoolProperty is always a bool; anything else (a mock,
        # a missing property) is not an open run.
        return scene is not None and getattr(scene, 'mixie_run_open', False) is True

    @staticmethod
    def set_run(scene, run_id: str, open: bool) -> None:
        """Single writer of the run state. Must be called from the main thread.

        ``open=True`` records ``run_id`` and keeps the scene active for worker
        scripts even when its turn is IDLE; ``open=False`` closes it (the id
        is dropped — a closed run is never addressed again).
        """
        if not scene or not hasattr(scene, 'mixie_run_open'):
            return
        open = bool(open)
        run_id = (run_id or "") if open else ""
        changed = (
            bool(scene.mixie_run_open) != open
            or (getattr(scene, 'mixie_run_id', "") or "") != run_id
        )
        was_open = bool(scene.mixie_run_open)
        scene.mixie_run_open = open
        if hasattr(scene, 'mixie_run_id'):
            scene.mixie_run_id = run_id
        turn_active = SessionManager.get_state(scene) in SessionManager._ACTIVE_TURN_STATES
        SessionManager._sync_active_scene(scene, turn_active)
        if was_open and not open:
            # The run is over (completed, cancelled, aborted): no card may keep
            # working. A turn end alone does not settle them — the workers on
            # the cards outlive the orchestrator's turn (finalize_turn skips
            # the settle while the run is open).
            try:
                from mixar.modules.agent_panel.core.cards import settle_running
                settle_running()
            except Exception:  # noqa: BLE001 — the panel never blocks the run
                pass
        if changed and logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"RUN [{scene.name}]: {'open' if open else 'closed'} {run_id[:8]}"
            )

    @classmethod
    def clear_all_runs(cls) -> None:
        """Close the run on every scene. Main thread only."""
        import bpy
        for scene in bpy.data.scenes:
            cls.set_run(scene, "", False)

    @staticmethod
    def get_session_id(scene) -> str:
        """Get session ID from a scene.

        Args:
            scene: bpy.types.Scene instance

        Returns:
            Session ID string, or empty string if not set
        """
        if not scene:
            return ""
        return getattr(scene, 'mixie_session_id', "")

    @property
    def instance_id(self) -> str:
        """Get the Blender instance ID (generated lazily on first access)."""
        import bpy
        wm = bpy.context.window_manager
        if not wm:
            logger.debug("No WindowManager context available")
            return ""
        if not hasattr(wm, 'mixie_instance_id'):
            logger.warning("mixie_instance_id property not registered yet")
            return ""
        if not wm.mixie_instance_id:
            wm.mixie_instance_id = str(uuid.uuid4())
            logger.debug(f"Generated instance_id: {wm.mixie_instance_id[:8]}...")
        return wm.mixie_instance_id

    # ========================================================================
    # Session Lifecycle (scene-explicit)
    # ========================================================================

    @staticmethod
    def start_session(scene, user_request: str) -> str:
        """Start or continue a session on a scene.

        Only generates a new session ID if one doesn't already exist.
        Sets state to BUSY.

        Args:
            scene: bpy.types.Scene instance
            user_request: The user's chat message

        Returns:
            Session ID (existing or newly generated), empty string if no scene
        """
        if not scene:
            logger.warning("No scene for start_session")
            return ""

        from .cat_activity import clear_activity
        clear_activity(scene)
        if not scene.mixie_session_id:
            scene.mixie_session_id = str(uuid.uuid4())
            logger.debug(f"NEW SESSION [{scene.name}]: session_id={scene.mixie_session_id[:8]}")
        else:
            logger.debug(f"CONTINUE SESSION [{scene.name}]: session_id={scene.mixie_session_id[:8]}")

        SessionManager.set_state(scene, SessionState.BUSY)
        return scene.mixie_session_id

    @staticmethod
    def set_connected(scene) -> None:
        """Mark a scene's session as connected (IDLE state).

        Args:
            scene: bpy.types.Scene instance
        """
        SessionManager.set_state(scene, SessionState.IDLE)

    @staticmethod
    def set_disconnected(scene) -> None:
        """Mark a scene's session as disconnected (OFFLINE).

        Args:
            scene: bpy.types.Scene instance
        """
        SessionManager.set_state(scene, SessionState.OFFLINE)

    @staticmethod
    def set_error(scene) -> None:
        """Set error state (OFFLINE) on a scene.

        Args:
            scene: bpy.types.Scene instance
        """
        SessionManager.set_state(scene, SessionState.OFFLINE)

    @staticmethod
    def is_connected(scene) -> bool:
        """Check if a scene's session is connected (not OFFLINE/CONNECTING).

        Args:
            scene: bpy.types.Scene instance

        Returns:
            True if connected
        """
        state = SessionManager.get_state(scene)
        return state not in (SessionState.OFFLINE, SessionState.CONNECTING)

    @staticmethod
    def clear_session_id(scene) -> None:
        """Clear session ID on a scene to force a new session.

        Args:
            scene: bpy.types.Scene instance
        """
        from .cat_activity import clear_activity
        clear_activity(scene)
        if scene and hasattr(scene, 'mixie_session_id'):
            scene.mixie_session_id = ""
        SessionManager.set_run(scene, "", False)
        logger.info("SESSION ID CLEARED: next message will create new session")

    @staticmethod
    def clear(scene) -> None:
        """Clear session state and reset to IDLE.

        Args:
            scene: bpy.types.Scene instance
        """
        from .cat_activity import clear_activity
        clear_activity(scene)
        if scene and hasattr(scene, 'mixie_session_id'):
            scene.mixie_session_id = ""
        SessionManager.set_run(scene, "", False)
        SessionManager.set_state(scene, SessionState.IDLE)

    def clear_streaming(self) -> None:
        """No-op: kept for backward compatibility."""
        pass

    # ========================================================================
    # Thread-Safe Helpers
    # ========================================================================

    @classmethod
    def has_active_session(cls) -> bool:
        """Check if any scene has an active agent session. Thread-safe.

        Safe to call from any thread (WebSocket, socket background).
        Used by connection_manager.on_script_execute to gate tool execution.

        Returns:
            True if at least one scene is BUSY/MODIFYING/AWAITING_INPUT or
            owns an open run (its workers build while the orchestrator idles)
        """
        with cls._active_scenes_lock:
            return len(cls._active_scenes) > 0

    # States a transport (WebSocket) drop may downgrade to OFFLINE. The active
    # turn states — BUSY / MODIFYING / AWAITING_INPUT — are deliberately
    # excluded: the agent turn lives on its own backend task and keeps
    # running through a WS blip, so its state must survive the reconnect.
    _DISCONNECT_DOWNGRADABLE = frozenset({SessionState.IDLE, SessionState.CONNECTING})

    @classmethod
    def on_transport_disconnect(cls, terminal: bool = False) -> None:
        """Apply the scene-state policy for a WebSocket disconnect.

        Must be called from the main thread (mutates scene properties).

        A TRANSIENT drop (``terminal=False`` — the WS client auto-reconnects
        within seconds) downgrades only IDLE/CONNECTING scenes to OFFLINE and
        preserves active turn states. Wiping BUSY/MODIFYING/AWAITING_INPUT
        here used to clear ``_active_scenes``, so after the silent reconnect
        every backend script was refused with "Agent session not active"
        while the status pill showed Connected/idle — the backend kept
        grinding whole build waves against those refusals (backend trace
        b0c909ab). The turn's lifecycle is owned by the agent stream
        (queue_processor), not by the WS transport.

        A TERMINAL disconnect (``terminal=True`` — auth failure, reconnection
        stopped) wipes every scene to OFFLINE and closes its run, as before.
        A transient drop preserves run state: the backend defers wake-ups
        while the socket is down and fires them on the next handshake.
        """
        if terminal:
            cls.clear_all_runs()
            cls.set_all_scenes_state(SessionState.OFFLINE)
        else:
            cls.set_all_scenes_state(
                SessionState.OFFLINE, only_from=cls._DISCONNECT_DOWNGRADABLE
            )

    @classmethod
    def set_all_scenes_state(cls, state: SessionState, only_from: Optional[set] = None) -> None:
        """Set state on all scenes. Must be called from main thread.

        Args:
            state: New state to set
            only_from: If provided, only update scenes currently in one of these states.
                       If None, update all scenes unconditionally.
        """
        import bpy
        for scene in bpy.data.scenes:
            if not hasattr(scene, 'mixie_chat_state'):
                continue
            if only_from is not None:
                current = cls.get_state(scene)
                if current not in only_from:
                    continue
            cls.set_state(scene, state)

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance."""
        with cls._active_scenes_lock:
            cls._active_scenes.clear()

    @staticmethod
    def get_status_message(scene) -> str:
        """Get human-readable status message for a scene's state.

        Args:
            scene: bpy.types.Scene instance

        Returns:
            Status message string
        """
        state = SessionManager.get_state(scene)
        return STATE_LABELS.get(state, "Unknown")


def get_session_manager() -> SessionManager:
    """Get the global SessionManager singleton."""
    return SessionManager()
