# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The client's view of the server's BYOK credential state.

Source of truth is a plain dict here; `wm.byok_*` is a mirror the C++ profile
card and the dialog draw from. Keeping the dict primary means a fetch that lands
before `byok_props` has registered its WindowManager properties (UI
auto-discovery is batched over several frames) is retained rather than silently
lost.

Deliberately NOT persisted to disk. The catalog is cacheable; this is not — it
carries the account's provider, model, masked key preview and, for Codex, the
ChatGPT account email. It is refetched per launch, which HTTP makes cheap and
reliable.

**The epoch exists for a real bug.** `_clear_byok_state_on_logout` wipes the
mirror synchronously while a fetch worker may be milliseconds from landing. Over
the WebSocket that mostly self-healed — logout dropped the socket, so the
in-flight RPC failed and a failed fetch is non-destructive. Over HTTP the request
completes with a still-valid bearer token and would write the PREVIOUS user's
provider and key preview back into the mirror, in front of the next user.
"""

import threading
from typing import Any, Dict, Optional

from mixar.config.logging_config import get_logger

from . import byok_client

logger = get_logger(__name__)

_FIELDS = (
    "byok_is_active",
    "byok_current_provider",
    "byok_current_model",
    "byok_current_supports_vision",
    "byok_key_preview",
)

_DEFAULTS: Dict[str, Any] = {
    "byok_is_active": False,
    "byok_current_provider": "",
    "byok_current_model": "",
    # Absent on older backends -> default to vision-capable, so we never show a
    # false "text-only" note.
    "byok_current_supports_vision": True,
    "byok_key_preview": "",
}

_lock = threading.Lock()
_state: Dict[str, Any] = dict(_DEFAULTS)
_epoch: int = 0


def snapshot() -> Dict[str, Any]:
    """Current state as a plain dict (safe to read from any thread)."""
    with _lock:
        return dict(_state)


def refresh() -> None:
    """Re-read the credential state from the server."""
    with _lock:
        epoch = _epoch

    def _done(success: bool, data, err):
        _apply_fetch_result(epoch, success, data, err)

    byok_client.fetch_state(on_done=_done)


def clear(wm=None) -> None:
    """Reset to defaults and invalidate any fetch already in flight.

    ``wm`` is the caller's live WindowManager when it has one — logout does,
    and passing it avoids re-deriving it from ``bpy.context``.
    """
    global _epoch, _state
    with _lock:
        _epoch += 1
        _state = dict(_DEFAULTS)
    apply_to_wm(wm)


def current_epoch() -> int:
    """The lifecycle epoch a caller should capture before starting async work."""
    with _lock:
        return _epoch


def apply_from_payload(data: Optional[dict], wm=None, *, epoch: Optional[int] = None) -> bool:
    """Adopt a server payload the caller already has (e.g. a save's echo).

    Used by the save path, which receives the authoritative state in its own
    response — issuing another GET afterwards would race the PUT's echo.

    ``epoch`` is the value of `current_epoch()` captured when the save was
    submitted. The PUT is async (up to 15 s); a save that completes AFTER a
    logout would otherwise write the logged-out account's provider and key
    preview back into the mirror. When ``epoch`` is given and a `clear()` has
    bumped it since, the payload is dropped and False is returned; the check
    and the store share one `_lock` acquisition, like `_apply_fetch_result`.
    """
    global _state
    parsed = _parse(data)
    with _lock:
        if epoch is not None and epoch != _epoch:
            logger.debug("BYOK save echo dropped (stale epoch)")
            return False
        _state = parsed
    apply_to_wm(wm)
    return True


def apply_to_wm(wm=None) -> None:
    """Mirror the state onto WindowManager properties, if they exist yet."""
    try:
        import bpy

        target = wm if wm is not None else bpy.context.window_manager
    except Exception:
        return
    if target is None:
        return
    current = snapshot()
    for field in _FIELDS:
        try:
            setattr(target, field, current[field])
        except Exception:
            # Properties not registered yet (UI auto-discovery is batched) —
            # the dict keeps the value and a later apply_to_wm picks it up.
            return



# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _parse(data) -> Dict[str, Any]:
    """Translate the server's `{byok_active, items}` into mirror fields.

    All items are identical per the backend contract (one value fanned out
    across roles), so index 0 is the whole story.
    """
    parsed = dict(_DEFAULTS)
    if not isinstance(data, dict):
        return parsed
    parsed["byok_is_active"] = bool(data.get("byok_active", False))
    items = data.get("items") or []
    if items and isinstance(items[0], dict):
        first = items[0]
        parsed["byok_current_provider"] = first.get("provider", "") or ""
        parsed["byok_current_model"] = first.get("model", "") or ""
        parsed["byok_current_supports_vision"] = bool(first.get("supports_vision", True))
        parsed["byok_key_preview"] = first.get("key_preview", "") or ""
    return parsed


def _apply_fetch_result(epoch: int, success: bool, data, err) -> None:
    """Main-thread fetch callback.

    A FAILED fetch leaves the state alone. Only the server retires a credential,
    and it says so through the success path (`byok_active: false`). Clearing on
    failure turns a transient miss into a session-long "Not configured" over a
    credential that is still stored and still being used.
    """
    global _state
    with _lock:
        if epoch != _epoch:
            logger.debug("BYOK state response dropped (stale epoch)")
            return
        if success:
            _state = _parse(data)
        else:
            logger.debug("BYOK state fetch failed (keeping cached state): %s", err)
            return
    apply_to_wm()
    _redraw()


def _redraw() -> None:
    try:
        from mixar.modules.common.utils.platform_utils import trigger_ui_redraw

        trigger_ui_redraw()
    except Exception as exc:
        logger.debug("BYOK state redraw failed: %s", exc)
