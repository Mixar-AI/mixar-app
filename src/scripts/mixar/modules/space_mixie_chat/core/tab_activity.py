# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which scene tabs have an agent working (counts for telemetry)."""


def tab_is_working(scene) -> bool:
    from ..constants import SessionState
    from .session import get_session_manager
    state = get_session_manager().get_state(scene)
    return state in (SessionState.BUSY, SessionState.MODIFYING) or bool(
        getattr(scene, 'mixie_run_open', False))


def tab_counts(current=None) -> tuple:
    """(user scene tabs, OTHER tabs whose agent is working right now)."""
    try:
        from ..ui.operators.scene_tab_ops import real_scenes
        tabs = real_scenes()
    except Exception:  # noqa: BLE001
        return 0, 0
    working = sum(1 for s in tabs if s is not current and tab_is_working(s))
    return len(tabs), working
