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
    sessions (BUSY/MODIFYING/AWAITING_INPUT). This is safe to read
    from background threads (CPython GIL protects set membership checks).
    """

    _instance: Optional["SessionManager"] = None
    # Thread-safe tracking of active scenes for background thread checks.
    # Updated only on main thread via set_state(). Read from any thread.
    _active_scenes: set = set()
    _active_scenes_lock = threading.Lock()

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

        if old_str == new_str:
            return

        scene.mixie_chat_state = new_str

        # Sync derived is_busy flag for C++ rendering code
        if hasattr(scene, 'mixie_chat_is_busy'):
            scene.mixie_chat_is_busy = (state == SessionState.BUSY)

        active_states = {SessionState.BUSY, SessionState.MODIFYING, SessionState.AWAITING_INPUT}
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

        # Update active scenes tracking (thread-safe)
        scene_name = scene.name
        with SessionManager._active_scenes_lock:
            if is_active:
                SessionManager._active_scenes.add(scene_name)
            else:
                SessionManager._active_scenes.discard(scene_name)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"STATE CHANGE [{scene_name}]: {old_str} -> {new_str}")

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
        if scene and hasattr(scene, 'mixie_session_id'):
            scene.mixie_session_id = ""
        logger.info("SESSION ID CLEARED: next message will create new session")

    @staticmethod
    def clear(scene) -> None:
        """Clear session state and reset to IDLE.

        Args:
            scene: bpy.types.Scene instance
        """
        if scene and hasattr(scene, 'mixie_session_id'):
            scene.mixie_session_id = ""
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

        Safe to call from any thread (WebSocket, SSE background).
        Used by connection_manager.on_script_execute to gate tool execution.

        Returns:
            True if at least one scene is BUSY/MODIFYING/AWAITING_INPUT
        """
        with cls._active_scenes_lock:
            return len(cls._active_scenes) > 0

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
