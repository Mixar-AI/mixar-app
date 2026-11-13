# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Fail the build if bundled runtime dependencies (trust, MCP, PDF) cannot import."""

import pypdfium2
import truststore
from jsonschema import Draft202012Validator
from mcp import ClientSession
from mcp.server import Server
from mcp.server.stdio import stdio_server

assert all((truststore, Draft202012Validator, ClientSession, Server, stdio_server))
# PDFium loads its own shared library: the import proves the wheel matched this
# platform (the app only advertises PDF support when it imports).
assert pypdfium2.PdfDocument
print("Bundled trust, MCP and PDF runtime imports passed")
