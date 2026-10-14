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
