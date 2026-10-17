# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""External tool execution protocol limits."""

CAPABILITY = "mcp_operations_v1"
BEGIN_OPERATION = "mcp.begin_operation"
END_OPERATION = "mcp.end_operation"
OPERATION_CONTEXT_KEY = "mcp_operation_id"
DEFAULT_TIMEOUT_SECONDS = 120
MAX_TIMEOUT_SECONDS = 600
MAX_ACTIVE_OPERATIONS = 32
RETIRED_OPERATION_SECONDS = 3600
#: Per-app setup lives on the website; the dialog copies the standard JSON.
SETUP_GUIDE_URL = "https://www.mixar.app/docs#connect-ai-apps"

#: Connect MCP sheet states (`ui/properties/connect_props.py`). Each
#: state has exactly one default button:
#:   IDLE    the app's setup, Add to <app> / Copy setup
#:   ADDING  the add runs on a worker thread; a busy primary, the sidebar locked
#:   ADDED   the recap (added, updated or already there) with one Done
#:   ERROR   the form again, the failure over a Try Again
CONNECT_STATE_ITEMS = (
    ('IDLE', "Idle", "Showing the selected app's setup"),
    ('ADDING', "Adding", "Adding Mixar to the app"),
    ('ADDED', "Added", "The app has Mixar; showing the recap"),
    ('ERROR', "Error", "Adding Mixar to the app failed"),
)
#: The sidebar's foot: any app that runs a local MCP server, in one of
#: `core/app_configs.FORMATS`.
OTHER_APP = 'OTHER'
#: App names are product names: a translation context with no catalog
#: entries keeps "Cursor" from being shown as a translated word.
PRODUCT_NAMES = "Mixar product name"
