# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Persisted telemetry consent preference."""

from mixar.config.config import add_config, get_config


def is_enabled() -> bool:
    """Usage analytics is enabled unless the user has explicitly opted out."""
    return bool(get_config().get("share_usage_data", True))


def set_enabled(enabled: bool) -> bool:
    return add_config("share_usage_data", bool(enabled))
