# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Persisted update preference: install updates when Mixar quits.

A per-user choice, so it lives in the user config overlay (``add_config``),
never in the build-generated bundled ``mixar.json`` whose ``updates``
section (``auto_download``, ``channel``) the build owns. On by default.
"""

from mixar.config.config import add_config, get_config

from ..constants import INSTALL_ON_QUIT_CONFIG_KEY


def install_on_quit_enabled() -> bool:
    """Install staged updates on quit (or at the next launch) without asking."""
    try:
        return bool(get_config().get(INSTALL_ON_QUIT_CONFIG_KEY, True))
    except Exception:  # noqa: BLE001 - an unreadable config keeps the default
        return True


def set_install_on_quit(enabled: bool) -> bool:
    """Persist the choice; False when the overlay could not be written."""
    return add_config(INSTALL_ON_QUIT_CONFIG_KEY, bool(enabled))
