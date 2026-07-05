# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Space Mixie Chat Module Constants

Centralized configuration values for the Mixie Chat module.
"""

from enum import Enum


# ============================================================================
# DEVELOPMENT MODE
# ============================================================================

# Set to True to bypass WebSocket connection and use dummy data for UI dev
DEV_MODE = False


# ============================================================================
# STARTUP
# ============================================================================

# Delay before agent connection attempts on startup (seconds)
STARTUP_DELAY_SECONDS = 1.0


# ============================================================================
# SCENE ROUTING
# ============================================================================

# The backend addresses every execute_script with a `session_id` that acts as a
# scene-routing key (backend: decorator.execute_script_on_instance / services).
# - "agent:{connection_id}" is the CONSTANT per-connection routing session used
#   for normal / sandbox mode. It intentionally matches NO scene.mixie_session_id
#   so the client follows in-script window.scene changes (active-scene follow).
# - An empty session_id has the same "no explicit scene" meaning.
# - Any OTHER non-empty session is a REAL per-scene target: either the user's
#   main scene mixie_session_id (a UUID v4 set by SessionManager.start_session)
#   or a throwaway lane scene keyed "agentlane:{parent}:{n}" (scene-build mode).
#   These MUST resolve to a scene or the script is rejected — running one against
#   the wrong (active) scene corrupts the user's work.
AGENT_ROUTING_SESSION_PREFIX = "agent:"     # non-pinned constant → active scene
AGENT_LANE_SESSION_PREFIX = "agentlane:"    # throwaway lane scene marker


def is_non_scene_routing_session(session_id: str) -> bool:
    """True for the non-pinned constant / empty routing session.

    These intentionally match no scene and follow the user's active scene.
    Every other non-empty session is a per-scene session that MUST resolve
    to a real scene or the script is rejected (see main_thread_executor).
    """
    return (not session_id) or session_id.startswith(AGENT_ROUTING_SESSION_PREFIX)


def is_lane_scene(scene) -> bool:
    """True if a scene is a throwaway agent-lane scene (never a restore target)."""
    return getattr(scene, 'mixie_session_id', '').startswith(AGENT_LANE_SESSION_PREFIX)


# ============================================================================
# SESSION STATES
# ============================================================================

class SessionState(Enum):
    """Session states for the chat workflow.

    Minimal 5-state model (no flags, all enum):
    - OFFLINE: Not connected (covers initial, disconnected, error states)
    - CONNECTING: WebSocket connection in progress
    - IDLE: Connected and ready to send messages
    - BUSY: Agent processing request (sending/receiving/executing)
    - MODIFYING: User typing modification feedback
    - AWAITING_INPUT: Agent paused on a request_user_input question
      (free-form text, choice buttons, or approval buttons)
    """
    OFFLINE = "offline"
    CONNECTING = "connecting"
    IDLE = "idle"
    BUSY = "busy"
    MODIFYING = "modifying"
    AWAITING_INPUT = "awaiting_input"


# EnumProperty items for scene.mixie_chat_state
# Must match SessionState enum values (uppercased)
SESSION_STATE_ITEMS = [
    ('OFFLINE', "Offline", "Not connected"),
    ('CONNECTING', "Connecting", "WebSocket connection in progress"),
    ('IDLE', "Idle", "Connected and ready"),
    ('BUSY', "Busy", "Agent processing request"),
    ('MODIFYING', "Modifying", "User typing modification feedback"),
    ('AWAITING_INPUT', "Awaiting Input", "Agent waiting for user input"),
]


# State labels for UI display
STATE_LABELS = {
    SessionState.OFFLINE: "Not Connected",
    SessionState.CONNECTING: "Connecting...",
    SessionState.IDLE: "Connected",
    SessionState.BUSY: "Working...",
    SessionState.MODIFYING: "Modifying...",
    SessionState.AWAITING_INPUT: "Awaiting Input...",
}


# ============================================================================
# JSON-RPC 2.0 METHODS (WebSocket communication)
# ============================================================================

class JSONRPCMethod:
    """JSON-RPC 2.0 method names for WebSocket communication."""
    # Client -> Server
    SYSTEM_HANDSHAKE = "system.handshake"
    SYSTEM_PING = "system.ping"

    # Server -> Client (requests - expect response)
    BLENDER_EXECUTE_SCRIPT = "blender.execute_script"
    # Server -> Client (request - sandbox lifecycle; handled by the parent only)
    AGENT_SANDBOX_CONTROL = "agent.sandbox_control"

    # Server -> Client (notifications - no response)
    AGENT_TOOL_START = "agent.tool_start"
    AGENT_TOOL_EXECUTING = "agent.tool_executing"
    AGENT_TOOL_END = "agent.tool_end"

    # Server -> Client (notifications push)
    NOTIFICATIONS_PUSH = "notifications.push"
    JOB_UPDATE = "job.update"
    # Client -> Server (notification RPC)
    NOTIFICATIONS_SYNC = "notifications.sync"
    NOTIFICATIONS_MARK_READ = "notifications.mark_read"
    NOTIFICATIONS_GET_UNREAD = "notifications.get_unread"
    JOB_SYNC = "job.sync"
    JOB_GET = "job.get"


# ============================================================================
# JSON-RPC ERROR CODES
# ============================================================================

class JSONRPCErrorCode:
    """Standard and custom JSON-RPC 2.0 error codes."""
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    SERVER_ERROR = -32000
    CONNECTION_ERROR = -32001
    TIMEOUT_ERROR = -32002
    HANDLER_ERROR = -32003
    NOT_AUTHENTICATED = -32004
    INVALID_CONNECTION = -32005
    BLENDER_ERROR = -32006


# ============================================================================
# WEBSOCKET CLOSE CODES
# ============================================================================

# Custom WebSocket close code for authentication failure
WS_CLOSE_AUTH_FAILED = 4001


# ============================================================================
# WEBSOCKET CONFIGURATION DEFAULTS
# ============================================================================

DEFAULT_WS_URL_TEMPLATE = "/api/agent/ws"
DEFAULT_RECONNECT_DELAY = 1.0
DEFAULT_MAX_RECONNECT_DELAY = 30.0
DEFAULT_PING_INTERVAL = 15.0
DEFAULT_QUEUE_POLL_INTERVAL = 0.1
EXECUTION_POLL_INTERVAL = 0.3  # Slower polling during tool execution

# ============================================================================
# SSE API ENDPOINTS
# ============================================================================

AGENT_CHAT_ENDPOINT = "/api/v1/blender/agent/chat"
AGENT_INPUT_ENDPOINT = "/api/v1/blender/agent/input"

# ============================================================================
# CONNECTION MANAGER SETTINGS
# ============================================================================

# Default timeout for HTTP requests (seconds)
DEFAULT_HTTP_TIMEOUT = 30.0

# SSE read timeout: maximum seconds between SSE events before disconnecting.
# Backend has a 600s timeout for long-running agent tools, so the client
# timeout must exceed that to avoid a race condition.
SSE_READ_TIMEOUT = 630.0

# ============================================================================
# UI CONSTANTS
# ============================================================================

CHAT_PLACEHOLDER_TEXT = "Chat messages will appear here..."
CHAT_INPUT_PLACEHOLDER = "Type your message..."

# ============================================================================
# PROPERTY DEFAULTS
# ============================================================================

CHAT_INPUT_DEFAULT = ""
CHAT_INPUT_MAXLEN = 10000

# ============================================================================
# IMAGE ATTACHMENT CONSTANTS
# ============================================================================

MAX_IMAGE_SIZE_MB = 10
MAX_IMAGE_SIZE_BYTES = MAX_IMAGE_SIZE_MB * 1024 * 1024
SUPPORTED_IMAGE_FORMATS = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif'}
THUMBNAIL_SIZE = (128, 128)
MAX_ATTACHMENTS_PER_MESSAGE = 5

# Security: Maximum image dimensions to prevent memory exhaustion attacks
# 16384x16384 is a reasonable max (common GPU texture limit)
MAX_IMAGE_DIMENSION = 16384

# ============================================================================
# MESSAGE LENGTH LIMITS
# ============================================================================

# Maximum length for chat messages to prevent memory/performance issues
MAX_MESSAGE_LENGTH = 100000  # 100KB of text

# ============================================================================
# TIMER / EXECUTION CONSTANTS
# ============================================================================

# Timer interval for SSE queue processing (~60fps for short content)
TIMER_INTERVAL = 1 / 60  # ~0.016s
# Throttled interval when streaming long content (~30fps)
# Yields more main thread time to Blender's event loop (pinch-to-zoom, etc.)
TIMER_INTERVAL_THROTTLED = 1 / 30  # ~0.033s
# Content length threshold (chars) to switch from 60fps to 30fps
TIMER_THROTTLE_CONTENT_THRESHOLD = 2000

# Timeout threshold for script execution warnings (seconds)
SCRIPT_TIMEOUT_THRESHOLD = 30.0

# ============================================================================
# SLOT EVENT PROCESSING
# ============================================================================

# Maximum content.append (streaming text) events processed per timer tick.
# Higher = text drains faster, but each tick takes longer (blocks main loop).
# 8 events/tick at 60fps ≈ 480 tokens/sec — well above Claude's output rate.
STREAMING_BATCH_LIMIT = 8

# Prefix for temporary placeholder bubble IDs (optimistic UI loading indicator).
# Used in chat_ops.py (creation) and slot_processor.py (cleanup).
TEMP_PLACEHOLDER_PREFIX = "temp_placeholder_"

