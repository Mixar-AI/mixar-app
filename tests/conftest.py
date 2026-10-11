# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fixtures shared by the standalone (outside-Blender) test files."""

from pathlib import Path

import pytest


@pytest.fixture
def set_addon_projects_root(monkeypatch):
    """Point the ``addon_projects_dir`` Preference at a folder (created).

    The add-on projects root is read from the Mixar Preferences group
    through one seam, ``workspace.preferred_root_value``; outside Blender
    that group is a MagicMock and reads as unset, so a test that needs a
    specific root patches the seam instead of faking the property group.
    """
    from mixar.modules.addon_project import workspace

    def _set(root):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(workspace, "preferred_root_value", lambda: str(root))
        return root

    return _set


@pytest.fixture
def byok_device_keys(monkeypatch):
    """BYOK keys kept on this computer, without a real keychain or socket.

    An in-memory keychain behind ``key_vault``, a signed-in account and a
    connected app (``device_save._app_connection_id``). Returns the dict the
    keychain writes to, keyed by entry name.
    """
    from mixar.modules.byok.core import device_save, key_vault

    store = {}

    def _backend():
        return (
            lambda name: store.get(name, ""),
            lambda name, value: store.__setitem__(name, value) or True,
            lambda name: store.pop(name, None) is not None or True,
        )

    monkeypatch.setattr(key_vault, "_backend", _backend)
    monkeypatch.setattr(key_vault, "_account_scope", lambda: "acct")
    monkeypatch.setattr(device_save, "_app_connection_id", lambda: "conn-1")
    return store
