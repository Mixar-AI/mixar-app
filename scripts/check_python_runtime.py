# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Fail the build if bundled transport dependencies cannot actually import."""

import truststore
from jsonschema import Draft202012Validator
from mcp import ClientSession
from mcp.server import Server
from mcp.server.stdio import stdio_server

assert all((truststore, Draft202012Validator, ClientSession, Server, stdio_server))
print("Bundled trust and MCP runtime imports passed")
