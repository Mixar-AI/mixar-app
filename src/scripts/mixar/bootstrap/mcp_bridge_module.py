# SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""mcp_bridge module bootstrap.

Starts the loopback MCP bridge HTTP server so an external MCP server (mcp/
at the repo root) can drive Mixar's sandboxed agent-execution surface
directly — replacing the hosted Mixie orchestrator with the MCP client's own
model (zero hosted agent tokens).

Enabled by default; set MIXAR_MCP_ENABLED=0 to opt out. The server binds
loopback only and supports an optional shared token (MIXAR_MCP_TOKEN).
"""

import os

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

_DISABLED_VALUES = {"0", "false", "no", "off"}


def _is_enabled() -> bool:
    from mixar.modules.mcp_bridge.constants import ENV_ENABLED

    return os.environ.get(ENV_ENABLED, "1").strip().lower() not in _DISABLED_VALUES


def register():
    try:
        if not _is_enabled():
            logger.info("mcp_bridge bootstrap: disabled via env, skipping")
            return
        from mixar.modules.mcp_bridge.core import server

        srv = server.start_server()
        if srv is None:
            # Bind failure / non-loopback host / port conflict — start_server
            # already logged the cause. Make the operator-facing consequence
            # explicit rather than logging "registered" as if it worked.
            logger.warning(
                "mcp_bridge bootstrap: bridge is NOT listening; MCP tool calls will "
                "fail until this is resolved (check for a port conflict on the bridge port)."
            )
        else:
            logger.debug("mcp_bridge bootstrap: registered")
    except Exception as e:  # never break startup
        logger.error("mcp_bridge bootstrap: FAILED - %s", e, exc_info=True)


def unregister():
    try:
        from mixar.modules.mcp_bridge.core import server

        server.stop_server()
    except Exception as e:
        logger.error("mcp_bridge bootstrap unregister failed: %s", e, exc_info=True)
