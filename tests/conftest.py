# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fixtures shared by the standalone (outside-Blender) test files."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_connector_directory(monkeypatch, tmp_path):
    """Keep every test away from the developer's real ``~/.mixar``.

    The MCP discovery and connector directories hang off one override.
    Restart & Update's quit path writes the connector's ``updating`` marker
    there, and a test that drives it (the install gate, the helper, the
    in-progress marker) would otherwise leave a real marker behind that
    stops Claude or Codex from cold-starting Mixar on this machine for the
    next 15 minutes. A test that wants a specific directory sets its own.
    """
    monkeypatch.setenv("MIXAR_MCP_DISCOVERY_DIR", str(tmp_path / "mixar-mcp"))


@pytest.fixture
def set_addon_projects_root(monkeypatch):
    """Point the ``addon_projects_dir`` setting at a folder (created).

    The add-on projects root is read from the per-user config through one
    seam, ``workspace.preferred_root_value``; a test that needs a specific
    root patches the seam instead of writing a real config overlay.
    """
    from mixar.modules.addon_project import workspace

    def _set(root):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(workspace, "preferred_root_value", lambda: str(root))
        return root

    return _set
