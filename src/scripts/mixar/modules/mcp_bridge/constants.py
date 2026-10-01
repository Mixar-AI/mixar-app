# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""External tool execution protocol limits."""

from mixar.modules.common.i18n import n_

CAPABILITY = "mcp_operations_v1"
AGENT_CAPABILITY = "mcp_agent_v1"
BEGIN_OPERATION = "mcp.begin_operation"
END_OPERATION = "mcp.end_operation"
OPERATION_CONTEXT_KEY = "mcp_operation_id"
DEFAULT_TIMEOUT_SECONDS = 120
MAX_TIMEOUT_SECONDS = 600
MAX_ACTIVE_OPERATIONS = 32
RETIRED_OPERATION_SECONDS = 3600
SETUP_CHOICES = (("CLAUDE_CODE", n_("Copy Claude Code Command")),
                 ("CLAUDE_DESKTOP", n_("Copy Claude Desktop Configuration")),
                 ("CODEX", n_("Copy Codex Configuration")))
