# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The client's view of the server's BYOK credential state.

Source of truth is a plain dict here; `wm.byok_*` is a mirror the C++ profile
card and the dialog draw from; the island's model chip and popup read the
picker mirrors `core/picker_mirror.py` writes from here. Keeping the dict primary means a fetch that lands before `byok_props`
has registered its WindowManager properties (UI auto-discovery is batched
over several frames) is retained rather than silently lost. Not persisted:
it carries the account's provider, model and masked key preview, and is
refetched per launch.

**The epoch** guards logout (a fetch or echo landing after `clear()` would
write the PREVIOUS account's provider back). **The request serial** guards
ordering: every write this process knows the answer of bumps it, and a GET
issued before it is dropped when it lands; while an island mutation is in
flight (`_pending`) no background fetch is issued and a second mutation is
refused. **A paused key** is a record in this device's store while the server
says inactive; `byok_key_resumable` / `byok_record_resumable` are derived
off-thread after every apply (`key_store.check_resumable_async`), the way
`byok_device_key_missing` is.
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
    "byok_device_key_missing",
    "byok_key_resumable",
)

_DEFAULTS: Dict[str, Any] = {
    "byok_is_active": False,
    "byok_current_provider": "",
    "byok_current_model": "",
    # Absent on older backends -> default to vision-capable, so we never show a
    # false "text-only" note.
    "byok_current_supports_vision": True,
    "byok_key_preview": "",
    # Server says active but THIS device holds no usable key (an upgrade from
    # a client that stored keys server-side, a second machine, or an expired
    # Codex sign-in). Derived from `key_store` after every successful apply;
    # the dialog then asks for the key only.
    "byok_device_key_missing": False,
    # Server says inactive but THIS device holds a key record it can re-send
    # (the island paused it): a key-tab pick resumes it with no dialog. Derived
    # from `key_store` after every successful apply; the provider and model
    # it names (not mirrored) prefill the dialog and the menu's wording.
    "byok_key_resumable": False,
    "byok_resume_provider": "",
    "byok_resume_model": "",
    # The record here could be re-sent (derived while active too): Mixie
    # pauses only such a key — a Local key (endpoint not in the record), a
    # revoked Codex sign-in or a record from a build that did not remember
    # the model would be orphaned by a pause, so Mixie opens the settings.
    "byok_record_resumable": False,
    # Whether a server payload has been applied since the last `clear()`.
    # Not mirrored. Before the cold-start fetch lands the default "inactive"
    # is not knowledge: a 409 `byok_key_required` in that window refreshes
    # the mirror (`byok_notice`) instead of flipping "Key needed on this
    # device" over a key that is on this device.
    "byok_state_loaded": False,
}

_RESUME_FIELDS = ("byok_key_resumable", "byok_resume_provider", "byok_resume_model",
                  "byok_record_resumable")
_lock = threading.Lock()
_state: Dict[str, Any] = dict(_DEFAULTS)
_epoch: int = 0
# One-shot main-thread callbacks for the next fetch outcome of the current
# epoch (`on_next_fetch`); a logout `clear()` drops them with the epoch.
_fetch_hooks: list = []
# The one island mutation that may be in flight: an in-place model switch
# (a key-tab pick), a pause or a resume (the model card's picks). While set, background fetches are held (their answer would predate
# the mutation) and a second mutation is refused.
_pending: Optional[Dict[str, Any]] = None
# Bumped by every write this process knows the answer of: a GET issued before
# it is dropped when it lands; its failure retry carries the serial too.
_request_serial: int = 0
_RETRY_DELAY_S = 15.0

def snapshot() -> Dict[str, Any]:
    """Current state as a plain dict (safe to read from any thread)."""
    with _lock:
        return dict(_state)


def refresh() -> None:
    """Re-read the credential state from the server (skipped while the island
    has a mutation in flight: its echo is the fresher answer, and
    `end_pending` re-issues the read when something waits on it)."""
    global _request_serial
    with _lock:
        if _pending is not None:
            return
        epoch = _epoch
        _request_serial += 1
        serial = _request_serial

    def _done(success: bool, data, err):
        _apply_fetch_result(epoch, success, data, err, serial=serial)

    byok_client.fetch_state(on_done=_done)


def on_next_fetch(callback) -> None:
    """Run ``callback(loaded: bool)`` on the main thread when the next fetch
    of the current epoch settles — True when the mirror now holds the
    server's state, False when the fetch failed (the mirror is unchanged).
    One shot. The chat's cold-start 409 handling waits here to resend the
    message that went out keyless (`space_mixie_chat/core/byok_notice.py`)."""
    with _lock:
        _fetch_hooks.append(callback)


def _fire_fetch_hooks(loaded: bool) -> None:
    with _lock:
        hooks, _fetch_hooks[:] = list(_fetch_hooks), []
    for hook in hooks:
        try:
            hook(loaded)
        except Exception as exc:  # noqa: BLE001 — one hook never blocks another
            logger.debug("BYOK fetch hook failed: %s", exc)


def _has_fetch_hooks() -> bool:
    with _lock:
        return bool(_fetch_hooks)


def clear(wm=None, *, loaded: bool = False) -> None:
    """Reset to defaults and invalidate any fetch already in flight. ``wm``
    is the caller's live WindowManager when it has one. ``loaded`` is True
    for a server-confirmed removal (DELETE landed: "inactive" is knowledge,
    so the next turn's 409 handling must not treat the mirror as unfetched)
    and False on logout, where nothing is known yet.
    """
    global _epoch, _state, _pending, _request_serial
    with _lock:
        _epoch += 1
        _request_serial += 1
        _pending = None
        _state = dict(_DEFAULTS, byok_state_loaded=loaded)
        _fetch_hooks[:] = []
    apply_to_wm(wm)
    if loaded:
        _check_resumable(snapshot())


def current_epoch() -> int:
    """The lifecycle epoch a caller should capture before starting async work."""
    with _lock:
        return _epoch


def apply_from_payload(data: Optional[dict], wm=None, *, epoch: Optional[int] = None) -> bool:
    """Adopt a server payload the caller already has (a save's echo): newer
    than any GET in flight, so the request serial is bumped. ``epoch`` is
    `current_epoch()` captured when the save was submitted; a payload that
    lands after a `clear()` (logout) is dropped and False returned.
    """
    global _state, _request_serial
    parsed = _parse(data)
    with _lock:
        if epoch is not None and epoch != _epoch:
            logger.debug("BYOK save echo dropped (stale epoch)")
            return False
        _carry_resumable(parsed, _state)
        _state = parsed
        _request_serial += 1
    apply_to_wm(wm)
    _check_device_key(parsed)
    _check_resumable(parsed)
    return True


def apply_removed(wm=None, *, epoch: Optional[int] = None) -> bool:
    """The server's rows are gone (a pause or removal landed): "nothing
    stored, LOADED", without touching the logout epoch (a save made right
    after keeps its echo); the resumable check that follows tells the island
    whether this device still holds the key."""
    return apply_from_payload({"byok_active": False, "items": []}, wm, epoch=epoch)


def set_device_key_missing(missing: bool) -> None:
    """Main thread: record whether this device holds a usable key."""
    global _state
    with _lock:
        if _state["byok_device_key_missing"] == bool(missing):
            return
        _state = dict(_state, byok_device_key_missing=bool(missing))
    apply_to_wm()
    _redraw()


def _check_device_key(parsed: Dict[str, Any]) -> None:
    """After a successful apply: ask the key store (worker thread) whether
    this device can actually sign the next turn. Inactive → never missing."""
    if not parsed["byok_is_active"]:
        set_device_key_missing(False)
        return
    epoch = current_epoch()

    def _done(missing: bool):
        if epoch == current_epoch():
            set_device_key_missing(missing)

    try:
        from . import key_store

        key_store.check_presence_async(parsed["byok_current_provider"], _done)
    except Exception as exc:  # noqa: BLE001 — a store fault is not a missing key
        logger.debug("BYOK device key check skipped: %s", exc)


def set_resumable(summary: Optional[Dict[str, str]]) -> None:
    """Main thread: record whether this device holds a key record the island
    can re-send (``summary`` = ``{"provider", "model"}``, else None)."""
    global _state
    with _lock:
        record = bool(summary)
        resumable = record and not _state["byok_is_active"]
        provider = (summary or {}).get("provider", "") if record else ""
        model = (summary or {}).get("model", "") if record else ""
        if (_state["byok_key_resumable"] == resumable
                and _state["byok_record_resumable"] == record
                and _state["byok_resume_provider"] == provider
                and _state["byok_resume_model"] == model):
            return
        _state = dict(_state, byok_key_resumable=resumable, byok_record_resumable=record,
                      byok_resume_provider=provider, byok_resume_model=model)
    apply_to_wm()
    _redraw()


def _check_resumable(parsed: Dict[str, Any]) -> None:
    """After a successful apply: ask the key store (worker thread) whether
    this device holds a record that can be re-sent — while inactive that is
    what the key tab resumes, while active it is what a Mixie pick may pause."""
    epoch = current_epoch()

    def _done(summary):
        if epoch == current_epoch():
            set_resumable(summary)

    try:
        from . import key_store

        key_store.check_resumable_async(_done)
    except Exception as exc:  # noqa: BLE001 — a store fault is "not resumable"
        logger.debug("BYOK resumable check skipped: %s", exc)


def _carry_resumable(parsed: Dict[str, Any], previous: Dict[str, Any]) -> None:
    """A payload says nothing about this device's record: keep the last
    answer, so the island does not flicker between an apply and the
    off-thread check that follows it. Lock held."""
    for field in _RESUME_FIELDS:
        parsed[field] = previous[field]
    parsed["byok_key_resumable"] = bool(previous["byok_record_resumable"]
                                        and not parsed["byok_is_active"])


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
    from . import picker_mirror
    picker_mirror.apply_to_wm(target)


# ---------------------------------------------------------------------------
# Island mutations: the chip's model switch, the toggle's pause / resume
# ---------------------------------------------------------------------------

def resumable(current: Optional[Dict[str, Any]] = None) -> bool:
    """A paused key this device can re-send: the key tab switches back to it
    with no dialog."""
    current = current if current is not None else snapshot()
    return bool(current["byok_key_resumable"] and not current["byok_is_active"])


def pausable(current: Optional[Dict[str, Any]] = None) -> bool:
    """A key in use that a resume could bring back after a pause: this
    device's record must be the ACTIVE provider's key. A record for another
    provider (the active key was saved on another computer) would pause the
    account's key and later resume a different one."""
    current = current if current is not None else snapshot()
    return bool(current["byok_is_active"] and current["byok_record_resumable"]
                and current["byok_resume_provider"]
                and current["byok_resume_provider"] == current["byok_current_provider"])


def resume_target() -> tuple:
    """``(provider, model)`` of the paused key, both "" when none."""
    current = snapshot()
    return ((current["byok_resume_provider"], current["byok_resume_model"])
            if resumable(current) else ("", ""))


def pending() -> str:
    """The island mutation in flight: "switch", "pause", "resume" or ""."""
    with _lock:
        return _pending["kind"] if _pending else ""


def switching() -> str:
    """The model an in-place switch is saving right now, or ""."""
    with _lock:
        return _pending["model"] if _pending and _pending["kind"] == "switch" else ""


def begin_switch(model: str, wm=None) -> bool:
    """Mark a model switch in flight (the chip names ``model`` until it
    lands); False when another mutation is already in flight."""
    global _pending, _request_serial
    with _lock:
        if _pending is not None:
            return False
        _pending = {"kind": "switch", "model": model}
        _request_serial += 1
    apply_to_wm(wm)
    return True


def begin_toggle(enabled: bool, wm=None) -> bool:
    """Mark a pause (``enabled`` False) or resume (True) in flight. The mirror
    is NOT flipped ahead of the server (a turn sent meanwhile reads it to
    decide whether to carry the key). False when another mutation is in
    flight, or for a resume with nothing to resume."""
    global _pending, _request_serial
    with _lock:
        if _pending is not None:
            return False
        if enabled and not (_state["byok_key_resumable"] and not _state["byok_is_active"]):
            return False
        _pending = {"kind": "resume" if enabled else "pause", "model": ""}
        _request_serial += 1
    apply_to_wm(wm)
    return True


def end_pending(wm=None) -> None:
    """The mutation landed (or failed); the caller adopts its echo or
    re-reads next. A read somebody waits on (`on_next_fetch`) is issued now."""
    global _pending, _request_serial
    with _lock:
        _pending = None
        _request_serial += 1
    apply_to_wm(wm)
    if _has_fetch_hooks():
        refresh()


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
    parsed["byok_state_loaded"] = True
    parsed["byok_is_active"] = bool(data.get("byok_active", False))
    items = data.get("items") or []
    if items and isinstance(items[0], dict):
        first = items[0]
        parsed["byok_current_provider"] = first.get("provider", "") or ""
        parsed["byok_current_model"] = first.get("model", "") or ""
        parsed["byok_current_supports_vision"] = bool(first.get("supports_vision", True))
        parsed["byok_key_preview"] = first.get("key_preview", "") or ""
    return parsed


def _apply_fetch_result(epoch: int, success: bool, data, err, *, serial=None) -> None:
    """Main-thread fetch callback. A FAILED fetch leaves the state alone
    (only the server retires a credential, through the success path) and is
    retried later. A fetch issued before a write this process made (an
    island mutation, a save / remove echo) is dropped — it would put the
    older state back; the mirror already holds newer server state, so
    whoever waited on the fetch is told so.
    """
    global _state
    with _lock:
        if epoch != _epoch:
            logger.debug("BYOK state response dropped (stale epoch)")
            return
        if _pending is not None or (serial is not None and serial != _request_serial):
            logger.debug("BYOK state response dropped (superseded)")
            superseded_loaded = bool(_state["byok_state_loaded"])
            held = _pending is not None
        else:
            superseded_loaded = None
            held = False
            if success:
                parsed = _parse(data)
                _carry_resumable(parsed, _state)
                _state = parsed
            else:
                logger.debug("BYOK state fetch failed (keeping cached state, retrying): %s", err)
    if superseded_loaded is not None:
        # Held by a mutation: `end_pending` re-issues the read. Superseded by
        # a newer READ before anything loaded (the cold-start 409 refresh
        # overtaking the login fetch): that read answers the hooks — firing
        # False here would trade the auto-resend for the key-missing card.
        if not held and superseded_loaded:
            _fire_fetch_hooks(True)
        return
    if not success:
        _fire_fetch_hooks(False)
        _schedule_retry(epoch, serial)
        return
    apply_to_wm()
    _redraw()
    _check_device_key(parsed)
    _check_resumable(parsed)
    _fire_fetch_hooks(True)


def _schedule_retry(epoch, serial) -> None:
    """Retry one failed read later; logout and any newer write cancel it."""
    try:
        import bpy
    except Exception:  # noqa: BLE001
        return

    def retry():
        with _lock:
            if epoch != _epoch or serial != _request_serial or _pending is not None:
                return None
        refresh()
        return None

    try:
        bpy.app.timers.register(retry, first_interval=_RETRY_DELAY_S)
    except Exception as exc:  # noqa: BLE001
        logger.debug("BYOK state retry not scheduled: %s", exc)


def _redraw() -> None:
    try:
        from mixar.modules.common.utils.platform_utils import trigger_ui_redraw
        trigger_ui_redraw()
    except Exception as exc:
        logger.debug("BYOK state redraw failed: %s", exc)
