# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Agent Connection Bootstrap Module.

Hooks into Blender startup to automatically establish JSON-RPC WebSocket
connection to the Adeveda Enterprises Private Limited agent backend.

This module is loaded by bootstrap/__init__.py during the startup sequence.
It schedules a delayed initialization to ensure all other systems are ready
before attempting to connect.
"""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Track whether the timer has been registered
_init_timer_registered = False



def _delayed_init() -> None:
    """Timer callback: fires once after the startup delay.

    Only initializes the ConnectionManager (generates instance_id via bpy
    property writes on the main thread).  Does NOT attempt to connect —
    the actual WebSocket connection is triggered by _auto_connect_websocket()
    in auth_ops.py after the auth check confirms a valid token.  Connecting
    here before login completes causes a race: the premature attempt sets
    state to CONNECTING, and the later (valid) attempt bails with "Already
    connected or connecting", leaving the connection permanently stuck.

    Returns:
        None to indicate the timer should not repeat.
    """
    try:
        from mixar.modules.space_mixie_chat.core.connection_manager import (
            get_connection_manager,
        )
        from mixar.modules.space_mixie_chat.constants import DEV_MODE

        if DEV_MODE:
            logger.debug("DEV_MODE enabled - skipping auto-connect")
            return None

        manager = get_connection_manager()

        # Initialize on the main thread: reads/generates instance_id via
        # bpy.types.WindowManager.mixie_instance_id (bpy property access).
        if not manager.initialize():
            logger.error("Failed to initialize ConnectionManager")
            return None

        logger.debug("ConnectionManager initialized — waiting for auth before connecting")

    except ImportError as e:
        logger.warning(f"Agent connection module not available: {e}")
    except Exception as e:
        logger.error("Failed to initialize agent connection: %s", e, exc_info=True)

    return None  # Run once, don't repeat


def register() -> None:
    """
    Called by bootstrap during startup.

    Schedules the delayed initialization timer.
    """
    global _init_timer_registered

    try:
        from mixar.modules.space_mixie_chat.constants import STARTUP_DELAY_SECONDS
        delay = STARTUP_DELAY_SECONDS
    except ImportError:
        delay = 2.0  # Default fallback

    if not _init_timer_registered:
        bpy.app.timers.register(
            _delayed_init,
            first_interval=delay,
            persistent=True,  # Survives file loads
        )
        _init_timer_registered = True
        logger.debug("Agent connection timer scheduled (delay: %ss)", delay)


def unregister() -> None:
    """
    Called by bootstrap during shutdown.

    Unregisters the timer and disconnects the WebSocket.
    """
    global _init_timer_registered

    try:
        from mixar.modules.space_mixie_chat.core.export_destination import (
            clear_all_destinations,
        )
        clear_all_destinations()
    except ImportError:
        pass

    try:
        if bpy.app.timers.is_registered(_delayed_init):
            bpy.app.timers.unregister(_delayed_init)
            logger.debug("Agent connection timer unregistered")

        try:
            from mixar.modules.space_mixie_chat.core.connection_manager import (
                get_connection_manager,
            )
            manager = get_connection_manager()
            manager.disconnect(update_session_state=False)
        except ImportError:
            pass  # Module not loaded, nothing to disconnect

        logger.debug("Agent connection shutdown complete")

    except Exception as e:
        logger.warning(f"Error during agent connection shutdown: {e}")

    _init_timer_registered = False
