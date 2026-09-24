# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Whether the interactive onboarding tour currently owns the screen.

Autoshow, toasts, the update prompt and the Zen/Engine switch all defer
to a running tour; this is the one check they share.
"""


def tour_running() -> bool:
    """True while the interactive onboarding tour owns the screen; a
    missing or half-loaded tour package reads as "not running"."""
    try:
        from mixar.modules.onboarding.core.tour import session as tour_session
        return bool(tour_session.is_running())
    except Exception:  # noqa: BLE001
        return False
