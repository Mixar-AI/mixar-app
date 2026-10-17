# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fixtures shared by the standalone (outside-Blender) test files."""

from pathlib import Path

import pytest


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
