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

# Safe retry schedule for an agent SSE request that could not establish a TCP
# connection at all.  ConnectError means the backend never accepted the turn,
# so retrying cannot duplicate agent work.  Mid-stream/read/write failures are
# deliberately excluded because their acceptance state is ambiguous.
SSE_CONNECT_RETRY_DELAYS = (1.0, 2.0, 4.0, 8.0, 15.0)


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
    # Liveness probe answered on the WEBSOCKET thread (never queued to the
    # main thread): the backend asks it before counting a script timeout
    # toward the "Blender stopped responding" breaker, so a long-but-healthy
    # script is distinguishable from a frozen app. Advertised in the handshake
    # as the "liveness" capability; older clients simply never answer it.
    BLENDER_LIVENESS = "blender.liveness"
    # Server -> Client (request - sandbox lifecycle; handled by the parent only)
    AGENT_SANDBOX_CONTROL = "agent.sandbox_control"
    # Server -> Client (request - relay one LLM HTTP call to the user's local
    # model server; handled off-thread, response deferred via queue_response)
    LLM_REQUEST = "llm.request"
    # Server -> Client (requests - capability-scoped local add-on workspace)
    ADDON_PROJECT_PREFIX = "addon_project."

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

# Disconnect reason the WS client passes to on_disconnected when it stops
# reconnecting because authentication failed. connection_manager treats this
# reason as TERMINAL (wipe all scene states to OFFLINE); every other reason
# is a transient drop the client auto-reconnects from, which must preserve
# active turn states (see SessionManager.on_transport_disconnect).
DISCONNECT_REASON_AUTH_FAILED = "Authentication failed - please login again"


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
AGENT_ATTACH_ENDPOINT = "/api/v1/blender/agent/chat/attach"
AGENT_FEEDBACK_ENDPOINT = "/api/v1/blender/agent/feedback"
AGENT_PARKED_TURN_ENDPOINT = "/api/v1/blender/agent/parked-turn"

# Feedback submission lifecycle shown inline on the rated message.
# Values are mirrored in C++ (mixie_chat_feedback.cc) — keep in sync.
FEEDBACK_STATUS_IDLE = 0
FEEDBACK_STATUS_SENDING = 1
FEEDBACK_STATUS_RECEIVED = 2
FEEDBACK_STATUS_FAILED = 3

# ============================================================================
# CONNECTION MANAGER SETTINGS
# ============================================================================

# Default timeout for HTTP requests (seconds)
DEFAULT_HTTP_TIMEOUT = 30.0

# WebSocket liveness: the client pings every ~15s and the server answers, so
# a healthy connection always receives SOMETHING within this window. Zero
# inbound traffic for this long means the TCP connection silently died
# (network drop, sleep/resume, NAT rebind) — sends still "succeed" into the
# kernel buffer on such a zombie, so only the recv side can detect it. On
# expiry the client PROBES first (see below) and tears the socket down only
# if the probe also gets no answer, then auto-reconnects.
WS_LIVENESS_TIMEOUT = 45.0

# Liveness grace probe: the receive thread starves whenever Blender's main
# thread holds the GIL through a long script/render, so on wake the liveness
# window can be expired even though the server kept the connection healthy
# the whole time (it tolerates long pong gaps precisely for this case). On
# expiry the client first sends a ping and waits this long for ANY inbound
# traffic before declaring the link dead — a genuinely dead TCP connection
# still tears down at WS_LIVENESS_TIMEOUT + this grace (~50s), while a
# GIL-starved wake-up proves the link alive within ~1s and carries on.
WS_LIVENESS_PROBE_GRACE = 5.0

# UI transport-staleness threshold: how long recv may be silent before the
# status surfaces (bubble pill, chat header) stop implying a healthy
# connection. A healthy connection carries at least a pong per ~15s ping, so
# ping interval + 5s grace of silence almost certainly means the network is
# gone — the pill flips to Reconnecting/Disconnected here (~5–20s after the
# drop) instead of waiting out the full teardown watchdog above. Deliberately
# a SEPARATE, earlier threshold: send-gating keeps using is_connected because
# a false "down" there would drop work, while a false "down" on a label is
# just a few seconds of pessimistic UI. Must stay well below
# WS_LIVENESS_TIMEOUT and above DEFAULT_PING_INTERVAL.
WS_UI_STALE_THRESHOLD = 20.0

# SSE read timeout: maximum seconds between BYTES on the stream before
# httpx declares it dead. The backend emits ": keepalive" comment lines
# every ~15s whenever the graph is silent (long LLM calls, long tools), so
# a healthy stream always carries bytes well within this window — a long
# silence means the TCP connection died (network drop, sleep/resume, NAT
# rebind). Was 630s (backend 600s tool timeout + margin) before keepalives
# existed, which left a dead mid-turn stream undetected for 10+ minutes.
# A false positive is harmless now: a read timeout mid-turn re-attaches via
# /agent/chat/attach (idempotent replay) instead of failing the turn.
SSE_READ_TIMEOUT = 75.0

# Re-attach after a mid-turn stream loss: total budget before giving up and
# failing the turn client-side. The backend keeps a disconnected turn running
# and buffers its events for replay, so a long outage is still recoverable.
ATTACH_RETRY_MAX_SECONDS = 900.0
# Per-attempt backoff; the last delay repeats while the budget lasts.
ATTACH_RETRY_DELAYS = (1.0, 2.0, 4.0, 8.0, 15.0)

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

# Project rules (scene.mixie_chat_rules) — persisted in the file and
# prepended to the first message of every new chat session. Bounded well
# below MAX_MESSAGE_LENGTH so rules + user prompt can never overflow.
# Must stay in lockstep with RULES_TEXT_MAX / the rules_text buffer in
# the C++ overlay (mixie_chat_rules_intern.hh / mixie_chat_layout_data.hh).
CHAT_RULES_MAXLEN = 10000

# ============================================================================
# '@' MENTION AUTOCOMPLETE
# ============================================================================

# Max suggestion rows in the dropdown. Must match FOOTER_MENTION_MAX_ROWS in
# mixie_chat_footer_constants.hh — the C++ dropdown never draws more rows.
MENTION_MAX_ITEMS = 6

# Max published query length in bytes (leading '@' included). Must match
# MENTION_QUERY_MAX in mixie_chat_footer_constants.hh.
MENTION_QUERY_MAXLEN = 96

# Max replacement text length. The C++ accept path reads insert_text into a
# 320-byte buffer (MIXIE_MENTION_INSERT_SIZE) and refuses longer values.
MENTION_INSERT_MAXLEN = 300

# ============================================================================
# IMAGE ATTACHMENT CONSTANTS
# ============================================================================

# Ceiling on the SOURCE file a user may attach. Attachments are downscaled and
# JPEG re-encoded before upload (core/attachment_compression.py), so this no
# longer bounds what goes on the wire — it only stops absurd inputs. 10 MB
# rejected ordinary 48 MP phone photos outright ("File too large") even though
# they compress to a few hundred KB; decode cost is bounded by MAX_DECODE_PIXELS
# in the compressor, not by this.
MAX_IMAGE_SIZE_MB = 25
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
# CHAT HISTORY ARCHIVE (core/chat_history.py)
# ============================================================================

# "New Chat" archives the current conversation to ~/.mixar/chat_history/
# instead of destroying it. Oldest sessions beyond this cap are pruned.
MAX_ARCHIVED_SESSIONS = 30
# Titles shown in the history popover — first line of the first user message.
CHAT_HISTORY_TITLE_MAXLEN = 48
# Per-session cap on image files copied into ~/.mixar/chat_media/<session>/.
# Beyond this, remaining images keep their original (possibly temp) paths.
CHAT_HISTORY_MEDIA_MAX_BYTES = 50 * 1024 * 1024

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

# Undo checkpoints for agent-executed scripts.
#
# Agent scripts run from a bpy.app.timers tick, whose context carries no
# window, and ed.undo_push polls ED_operator_screenactive (window + screen).
# The bare push therefore failed and was silently swallowed: an agent turn
# used to get NO undo checkpoint at all ("undo the texturing and revert to
# the default model" was unservable). The executor now retries the push
# inside a borrowed window, so checkpoints actually exist — and their
# granularity/cost is governed here.
#
# AGENT_UNDO_GROUP_PER_TURN
#   False (default): every script gets its own checkpoint (bounded by the cap
#   below), so Ctrl-Z steps back through a turn one tool at a time — e.g.
#   revert just the applied texturing and keep the build.
#   True: one shared checkpoint per agent turn — the pre-turn state is one
#   Ctrl-Z away and undo memory stays flat in very heavy scenes, at the price
#   of all-or-nothing undo.
# Turn boundaries come from queue_processor: begin_agent_turn on the first
# streamed event, end_agent_turn on stream complete/error (and on abort /
# file load), so a checkpoint-less turn cannot leak into the next one.
AGENT_UNDO_GROUP_PER_TURN = False

# Per-script checkpoints are capped per turn. Blender keeps U.undosteps
# (32 by default) memfile steps, so an uncapped long turn would evict the
# pre-turn checkpoint — the one that must survive so Ctrl-Z can return to the
# scene as it was before the agent touched it. The first push of a turn is
# always that pre-turn state (execute() pushes BEFORE running the script);
# once the cap is reached later scripts stop pushing and share the last
# checkpoint. Only successful pushes count, so a failed push is retried by
# the next script.
AGENT_UNDO_MAX_CHECKPOINTS_PER_TURN = 8

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
