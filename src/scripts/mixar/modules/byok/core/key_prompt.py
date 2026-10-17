# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""A "key needed" request for the AI Provider Settings dialog.

The chat's key-missing card (`space_mixie_chat/core/byok_card.py`) opens the
dialog with a prefilled provider and model, the credential field focused,
and something to do once a save lands — resend the message the refusal
stopped. The dialog operator cannot take arguments across a props dialog,
so the request lives here between the click and the dialog's ``invoke``.

Lifecycle: `request` (the card) → `take` (the dialog's invoke; the request
is "open" from here) → `notify_saved` (a successful save runs the callback
once) or `dismiss` (the dialog closed without a save). Process-local, never
persisted, holds no key material. Main thread only.
"""

from typing import Callable, Optional

FOCUS_KEY = "key"
FOCUS_CODEX_PATH = "codex_path"
FOCUS_LOCAL_KEY = "local_key"

_pending: Optional[dict] = None
_open = False


def request(provider: str, model: str, focus: str, on_saved: Optional[Callable[[], None]]) -> None:
    """Arm the next dialog open with a prefill, a field to focus and a
    callback for the first successful save."""
    global _pending, _open
    _pending = {"provider": provider or "", "model": model or "", "focus": focus or FOCUS_KEY,
                "on_saved": on_saved}
    _open = False


def take() -> Optional[dict]:
    """The dialog's invoke: the armed request (prefill fields only), or None.
    From here the request is open until the dialog saves or closes."""
    global _open
    if _pending is None:
        return None
    _open = True
    return {key: _pending[key] for key in ("provider", "model", "focus")}


def is_open() -> bool:
    """True while a dialog opened from a request is on screen: the form
    draws in its key-only state with the credential field focused."""
    return _open and _pending is not None


def focus_is(field: str) -> bool:
    return is_open() and _pending.get("focus") == field


def notify_saved() -> None:
    """A save landed: run the request's callback once and forget it."""
    global _pending, _open
    current, _pending, _open = _pending, None, False
    if current is not None and current.get("on_saved") is not None:
        current["on_saved"]()


def dismiss(*, saving: bool = False) -> None:
    """The dialog closed. A save still in flight keeps the request so its
    echo can resend; anything else forgets it."""
    global _pending, _open
    if saving and _open:
        return
    _pending, _open = None, False


def reset() -> None:
    dismiss()
