# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Composer hints while the agent works: steering and parallel scene tabs.

While a turn runs the island composer shows a busy placeholder instead of
"Describe your scene here...". Each fresh turn picks one hint; a hint retires
for good on this device once its feature has been used ``RETIRE_AFTER``
times, and once both retire the composer keeps the short steer line.

The hint text lives in ``WindowManager.mixie_chat_busy_hint`` as an English
template; the C++ island (``agent_ui_state.cc``) translates it per draw and
falls back to its own steer line while the property is empty.

Usage counts persist in the per-user config overlay under ``agent_tips``,
written on a worker thread (the overlay write is file I/O).
"""
import threading

from mixar.modules.common.i18n import n_

TIP_STEER = 'steer'
TIP_PARALLEL = 'parallel'
TIP_DEFAULT = 'default'
BUSY_HINTS = {
    TIP_STEER: n_("Mixie is working. Type here to steer it..."),
    TIP_PARALLEL: n_("Ctrl+` opens another scene with its own agent"),
    TIP_DEFAULT: n_("Type here to steer Mixie..."),
}
RETIRE_AFTER = 2
CONFIG_KEY = 'agent_tips'
WM_PROP = 'mixie_chat_busy_hint'

_state = {'turns': 0, 'current': ''}
_lock = threading.Lock()


def _counts() -> dict:
    try:
        from mixar.config.config import get_config
        raw = get_config().get(CONFIG_KEY) or {}
        return {k: int(v) for k, v in raw.items() if k in (TIP_STEER, TIP_PARALLEL)}
    except Exception:  # noqa: BLE001 — a hint never blocks a turn
        return {}


def active_tips() -> list:
    counts = _counts()
    return [t for t in (TIP_STEER, TIP_PARALLEL) if counts.get(t, 0) < RETIRE_AFTER]


def pick_busy_hint() -> str:
    """The tip id for the turn that is starting; alternates between the
    tips that have not retired."""
    tips = active_tips()
    if not tips:
        return TIP_DEFAULT
    tip = tips[_state['turns'] % len(tips)]
    _state['turns'] += 1
    return tip


def arm_busy_hint(context) -> str:
    """Called when a fresh turn starts: choose and publish this turn's hint."""
    tip = pick_busy_hint()
    _state['current'] = tip
    wm = getattr(context, 'window_manager', None)
    if wm is not None and hasattr(wm, WM_PROP):
        setattr(wm, WM_PROP, BUSY_HINTS[tip])
    return tip


def current_hint() -> str:
    """The tip id the composer showed for the running turn ('' before any)."""
    return _state['current']


def note_used(tip: str) -> None:
    """The user used ``tip``'s feature; persist the count off the main thread
    until the tip retires."""
    if tip not in (TIP_STEER, TIP_PARALLEL):
        return
    counts = _counts()
    if counts.get(tip, 0) >= RETIRE_AFTER:
        return
    counts[tip] = counts.get(tip, 0) + 1

    def _write():
        with _lock:
            try:
                # The newest counts at write time: two quick uses never let
                # an older thread overwrite a newer count.
                from mixar.config.config import add_config, get_config
                add_config(CONFIG_KEY, dict(get_config().get(CONFIG_KEY) or counts))
            except Exception:  # noqa: BLE001
                pass

    # The live config dict updates synchronously so the next pick sees it.
    try:
        from mixar.config.config import get_config
        get_config()[CONFIG_KEY] = dict(counts)
    except Exception:  # noqa: BLE001
        pass
    threading.Thread(target=_write, name='mixar-agent-tips', daemon=True).start()


def note_send(scene, steered: bool) -> None:
    """A message went out: count steering, and parallel work when another
    tab's agent is busy at the same time."""
    if steered:
        note_used(TIP_STEER)
    if tab_counts(scene)[1]:
        note_used(TIP_PARALLEL)


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
