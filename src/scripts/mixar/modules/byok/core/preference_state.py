# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The client's view of the account's hosted agent-model pick.

Modelled on `credential_state.py`, for the same reasons: a plain dict here is
the source of truth and `wm.mixar_agent_model_*` is a mirror, so a fetch that
lands before `agent_model_props` has registered its WindowManager properties
(UI auto-discovery is batched over several frames) is retained rather than
silently lost.

The C++ footer button and the island chip read the mirror — `..._label` is what
they draw and `..._byok_active` is what greys them out — so the property names
are a cross-language contract.

**The dict's `mixar_agent_model_label` is the MODEL-ONLY label; the WM property
of the same name receives the COMPOSED chip text** (`chip_text()`, built by
`model_menu.chip_label` from the label, the saved thinking level and the BYOK
flag: "GPT 5.6 Sol · High", or the BYOK indicator while a user key overrides
the pick). Composing at the mirror boundary keeps the C++ side a plain string
reader and the dict a faithful copy of the server payload.

Not persisted to disk. It is per-account, the endpoint is `no-store`, and it is
one small request on login.

**The epoch exists for a real bug**, the same one `credential_state` documents:
logout wipes the mirror synchronously while a PUT worker may be milliseconds
from landing. The request completes with a still-valid bearer token and would
write the PREVIOUS account's pick back into the mirror, in front of the next
user. It also guards the *revert* path — a failed save must not restore a pick
that a logout has already invalidated.
"""

import threading
from typing import Any, Dict, Optional

from mixar.config.logging_config import get_logger

from . import model_menu, preference_client

logger = get_logger(__name__)

_FIELDS = (
    "mixar_agent_model_provider",
    "mixar_agent_model_id",
    "mixar_agent_model_label",
    "mixar_agent_model_thinking",
    "mixar_agent_model_byok_active",
    "mixar_agent_model_eligible",
)

_DEFAULTS: Dict[str, Any] = {
    "mixar_agent_model_provider": "",
    "mixar_agent_model_id": "",
    # Empty label = "no pick yet"; the button falls back to "Mixie".
    "mixar_agent_model_label": "",
    # Empty thinking = the model's own default, NOT "thinking off".
    "mixar_agent_model_thinking": "",
    "mixar_agent_model_byok_active": False,
    # Absent on older backends -> assume eligible, so we never grey out a pick
    # the server is happily resolving.
    "mixar_agent_model_eligible": True,
}

_lock = threading.Lock()
_state: Dict[str, Any] = dict(_DEFAULTS)
_epoch: int = 0
_request_serial: int = 0
_mutating: bool = False
_RETRY_DELAY_S = 15.0
PENDING_MESSAGE = "Saving agent model… Please wait before sending or changing models."


def mutation_pending() -> bool:
    with _lock:
        return _mutating


def begin_mutation() -> bool:
    """Serialize writes and invalidate every read/retry from before this write."""
    global _mutating, _request_serial
    with _lock:
        if _mutating:
            return False
        _mutating = True
        _request_serial += 1
    _redraw()
    return True


def end_mutation(epoch: int) -> bool:
    """Only the submitting account may release the send/write barrier."""
    global _mutating
    with _lock:
        if epoch != _epoch:
            return False
        _mutating = False
    _redraw()
    return True


def snapshot() -> Dict[str, Any]:
    """Current state as a plain dict (safe to read from any thread)."""
    with _lock:
        return dict(_state)


def refresh() -> None:
    """Re-read the saved pick from the server."""
    global _request_serial
    with _lock:
        if _mutating:
            return
        epoch = _epoch
        _request_serial += 1
        serial = _request_serial

    def _done(success: bool, data, err):
        _apply_fetch_result(epoch, success, data, err, serial=serial)

    preference_client.fetch_preference(on_done=_done)


def clear(wm=None) -> None:
    """Reset to defaults and invalidate any request already in flight.

    Called from `auth_hooks.invalidate_agent_settings()` and NOWHERE else —
    clearing the same state from two places gave an in-flight worker two
    orderings to win in (see the note in
    `space_mixie_chat/ui/operators/auth_ops.py`).
    """
    global _epoch, _state, _mutating, _request_serial
    with _lock:
        _epoch += 1
        _request_serial += 1
        _mutating = False
        _state = dict(_DEFAULTS)
    apply_to_wm(wm)


def current_epoch() -> int:
    """The lifecycle epoch a caller should capture before starting async work."""
    with _lock:
        return _epoch


def apply_from_payload(data: Optional[dict], wm=None, *, epoch: Optional[int] = None) -> bool:
    """Adopt a server payload the caller already has (a save's echo, or a GET).

    Returns False when ``epoch`` is given and a `clear()` has bumped it since —
    the payload is then dropped. The check and the store share one `_lock`
    acquisition, like `_apply_fetch_result`.
    """
    global _state
    parsed = _parse(data)
    with _lock:
        if epoch is not None and epoch != _epoch:
            logger.debug("Agent model preference payload dropped (stale epoch)")
            return False
        _state = parsed
    apply_to_wm(wm)
    return True


def apply_local(values: Dict[str, Any], wm=None, *, epoch: Optional[int] = None) -> bool:
    """Write mirror fields the client already knows, without a round trip.

    Two callers: the picker's OPTIMISTIC write (the label flips the instant the
    row is clicked, so the menu never feels like it swallowed the click), and
    the REVERT when the PUT comes back non-2xx. Unknown keys are ignored;
    absent keys keep their current value, so a revert can restore exactly the
    snapshot it captured.
    """
    global _state
    with _lock:
        if epoch is not None and epoch != _epoch:
            logger.debug("Agent model preference local write dropped (stale epoch)")
            return False
        merged = dict(_state)
        for field in _FIELDS:
            if field in values:
                merged[field] = values[field]
        _state = merged
    apply_to_wm(wm)
    # Both surfaces live in their OWN windows (the Mixie Chat footer and the
    # Agent Bubble island), and a menu click only redraws the one it closed
    # over. Without this the other surface keeps the old label — and, worse,
    # the REVERT path would leave the user reading a model the server just
    # refused, which is the whole thing the optimistic write owes them.
    _redraw()
    return True


def chip_text() -> str:
    """The composed label the island chip draws (what the WM `_label` holds)."""
    current = snapshot()
    return model_menu.chip_label(
        current["mixar_agent_model_label"],
        current["mixar_agent_model_thinking"],
        bool(current["mixar_agent_model_byok_active"]),
    )


def apply_to_wm(wm=None) -> None:
    """Mirror the state onto WindowManager properties, if they exist yet.

    `mixar_agent_model_label` is written as the composed chip text — see the
    module docstring; every other field is copied verbatim.
    """
    try:
        import bpy

        target = wm if wm is not None else bpy.context.window_manager
    except Exception:
        return
    if target is None:
        return
    current = snapshot()
    current["mixar_agent_model_label"] = chip_text()
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
    """Translate `{byok_active, items:[...]}` into mirror fields.

    The desktop writes one pick under `role: "default"`, so that item is the
    whole story; index 0 is the fallback for a backend that answers with a
    single un-roled item.
    """
    parsed = dict(_DEFAULTS)
    if not isinstance(data, dict):
        return parsed
    parsed["mixar_agent_model_byok_active"] = bool(data.get("byok_active", False))

    items = [item for item in (data.get("items") or []) if isinstance(item, dict)]
    if not items:
        return parsed
    chosen = next(
        (item for item in items if item.get("role") == preference_client.DEFAULT_ROLE),
        items[0],
    )
    parsed["mixar_agent_model_provider"] = chosen.get("provider") or ""
    parsed["mixar_agent_model_id"] = chosen.get("model") or ""
    parsed["mixar_agent_model_label"] = model_menu.display_model_label(
        parsed["mixar_agent_model_provider"], parsed["mixar_agent_model_id"],
        chosen.get("label") or "",
    )
    parsed["mixar_agent_model_thinking"] = chosen.get("thinking_level") or ""
    parsed["mixar_agent_model_eligible"] = bool(chosen.get("eligible", True))
    return parsed


def _apply_fetch_result(epoch: int, success: bool, data, err, *, serial=None) -> None:
    """Main-thread fetch callback.

    A FAILED fetch leaves the state alone: only the server retires a pick, and
    it says so through the success path. Clearing on failure would turn a
    transient miss into a session-long default label over a pick that is stored and
    still being resolved on every turn.
    """
    global _state
    with _lock:
        if epoch != _epoch or _mutating:
            return
        if serial is not None and serial != _request_serial:
            return
        if success:
            _state = _parse(data)
    if not success:
        logger.debug("Agent model preference fetch failed (retrying): %s", err)
        _schedule_retry(epoch, serial)
        return
    apply_to_wm()
    _redraw()


def _schedule_retry(epoch, serial) -> None:
    """Retry independently of catalog ETags; logout/new work cancels the ticket."""
    import bpy

    def retry():
        with _lock:
            if epoch != _epoch or serial != _request_serial or _mutating:
                return None
        refresh()
        return None

    bpy.app.timers.register(retry, first_interval=_RETRY_DELAY_S)


def _redraw() -> None:
    try:
        from mixar.modules.common.utils.platform_utils import trigger_ui_redraw

        trigger_ui_redraw()
    except Exception as exc:
        logger.debug("Agent model preference redraw failed: %s", exc)
