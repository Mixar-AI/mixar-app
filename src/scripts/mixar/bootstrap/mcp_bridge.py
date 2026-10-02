# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Desktop MCP connection and scoped external-operation lifecycle."""


def register():
    from mixar.modules.mcp_bridge.core import lease, runtime
    lease.register()
    runtime.register()


def unregister():
    from mixar.modules.mcp_bridge.core import lease, runtime
    runtime.unregister()
    lease.unregister()
