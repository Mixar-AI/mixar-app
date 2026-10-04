# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""MCP tests never touch the user's real ~/.mixar connector folder.

The launcher saves the backend tool list there (tool_snapshot) whenever it
fetches one, so a fake catalog in a test would otherwise replace the user's.
Tests that set their own MIXAR_MCP_DISCOVERY_DIR still win.
"""

import pytest


@pytest.fixture(autouse=True)
def isolated_connector_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("MIXAR_MCP_DISCOVERY_DIR", str(tmp_path / "mixar-mcp" / "discovery"))
