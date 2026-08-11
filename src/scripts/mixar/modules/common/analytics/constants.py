# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Product telemetry limits and event names."""

BATCH_SIZE = 50
FLUSH_INTERVAL_SECONDS = 10.0
MAX_QUEUE_SIZE = 1000
MAX_PROPERTIES = 32
SHUTDOWN_TIMEOUT_SECONDS = 2.0

EVENT_OPERATOR = "product.operator"
EVENT_MOODBOARD_PANEL = "moodboard.panel_changed"
EVENT_MOODBOARD_SIDEBAR = "moodboard.sidebar_toggled"
EVENT_CHAT_MODE = "agent.mode_changed"
EVENT_CHAT_HISTORY = "agent.history_toggled"
EVENT_MESSAGE_SENT = "agent.message_sent"
EVENT_BUBBLE_STATE = "agent_bubble.state_changed"
EVENT_BUBBLE_EXPAND = "agent_bubble.expand_toggled"
EVENT_EXPORT = "export.completed"
EVENT_EXPORT_INITIATED = "export.initiated"
EVENT_IMPORT_INITIATED = "import.initiated"
EVENT_SESSION_STARTED = "app.session_started"
EVENT_SESSION_ENDED = "app.session_ended"
EVENT_TELEMETRY_ENABLED = "telemetry.enabled"
EVENT_UI_MODE = "workspace.mode_changed"
EVENT_WORKSPACE = "workspace.switched"
EVENT_DRAFT_ABANDONED = "moodboard.draft_abandoned"
EVENT_OUTPUT_LANDED = "generation.output_landed"
EVENT_GENERATION_REJECTED = "generation.rejected"
EVENT_ONBOARDING_STARTED = "onboarding.started"
EVENT_ONBOARDING_STEP = "onboarding.step_changed"
EVENT_ONBOARDING_FINISHED = "onboarding.finished"

# generation.rejected only fires when an undo / delete lands within this
# many seconds of a generation or agent output arriving in the scene.
REJECTION_WINDOW_SECONDS = 60.0

# Workspace names can be user-authored; anything outside this allowlist is
# reported as "custom" so a personal workspace name never leaves the machine.
WORKSPACE_NAME_ALLOWLIST = frozenset({
    "Zen Mode",
    "AI Mode",
    "Layout",
    "Modeling",
    "Sculpting",
    "UV Editing",
    "Texture Paint",
    "Texturing",
    "Shading",
    "Animation",
    "Rendering",
    "Compositing",
    "Geometry Nodes",
    "Scripting",
    "2D Animation",
    "2D Full Canvas",
})

# Production showed 91% of product.operator traffic was repeated machinery,
# not deliberate user actions; keep these implementation helpers out entirely.
# bubble_header_drag is a modal driver whose meaningful outcome (pill toggle)
# is already reported as agent_bubble.state_changed.
IGNORED_OPERATORS = frozenset({
    "notification.toast_hover",
    # Fires success=false on every actionless toast click — chrome, not usage.
    "notification.toast_click",
    "mixie_chat.prune_render_cache",
    "mixar_byok.fetch_models_catalog",
    "mixar_byok.fetch_state",
    "mixar.agent_viewport_block",
    "mixar.bubble_block_context_menu",
    "mixar.bubble_header_drag",
    "mixar.onboarding_card",
})
