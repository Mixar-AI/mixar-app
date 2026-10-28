# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Switch the model your API key runs on, from the island card's key tab.

The key is on this computer (`core/key_store`), never typed again and never
re-entered: `byok_client.resave_stored_key` re-sends it to `PUT /agent/byok`
on the new model of the same provider (a Codex sign-in is read from the
CLI's file and renewed when stale, exactly as before a turn), and the server
re-validates it like a fresh save.

While the request is in flight the chip names the target model, dimmed, and
the card's rows are disabled (`credential_state.begin_switch`; one island
mutation at a time, shared with pause and resume). Success adopts
the server's echo exactly like a dialog save; a failure keeps the stored
model and says why in a toast. Nothing here opens the dialog.

`set_level` changes only the key's thinking level, from the same card's
level rows: `byok_client.set_thinking_level` (`PATCH /agent/byok`) sends no
key and re-validates nothing; the same in-flight mark, echo and toast apply.
Switching the model sends no level, so the new model starts on its default.

While a turn is in flight the switch is refused (`mixar.agent_pick`'s
`turn_in_flight` gate): the backend bound that turn's model when it started,
so the change would apply only to the next message while the chip named the
new one.
"""

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_

from ...core import byok_client, credential_state, preference_state

logger = get_logger(__name__)

SWITCH_TOAST_ID = "byok_switch_model"
SWITCH_TITLE = n_("Couldn't switch model")
#: The hosted level picker's wording for the same failure (agent_model_ops).
LEVEL_TITLE = n_("Could not change model")


def switch(wm, model: str) -> bool:
    """Re-send the key in use on ``model``; False when nothing started (a
    dialog save / removal, a hosted pick or another island mutation is in
    flight). Run by the island popup's `mixar.agent_pick`."""
    if byok_client.mutation_in_flight() or preference_state.mutation_pending():
        return False
    epoch = credential_state.current_epoch()
    if not credential_state.begin_switch(model, wm):
        return False
    _redraw()

    def _done(success, data, err):
        _on_switch_done(success, data, err, epoch)

    byok_client.resave_stored_key(model, on_done=_done)
    return True


def set_level(wm, level: str) -> bool:
    """Save ``level`` as the thinking level of the key in use; False when
    nothing started (as `switch`). Run by the island popup's `mixar.agent_pick`."""
    if byok_client.mutation_in_flight() or preference_state.mutation_pending():
        return False
    epoch = credential_state.current_epoch()
    model = credential_state.snapshot()["byok_current_model"]
    if not credential_state.begin_switch(model, wm, kind="level"):
        return False
    _redraw()

    def _done(success, data, err):
        _on_switch_done(success, data, err, epoch, title=LEVEL_TITLE)

    byok_client.set_thinking_level(level, on_done=_done)
    return True


def _on_switch_done(success, data, err, epoch, *, title=SWITCH_TITLE):
    """Main-thread callback: adopt the echo, or re-read and explain."""
    try:
        if credential_state.current_epoch() != epoch:
            return  # logged out meanwhile; `clear()` already reset everything
        credential_state.end_pending()
        if success:
            if credential_state.apply_from_payload(data or {}, epoch=epoch):
                preference_state.refresh()
                snap = credential_state.snapshot()
                logger.info("BYOK model switched: provider=%s model=%s",
                            snap["byok_current_provider"], snap["byok_current_model"])
        else:
            logger.warning("BYOK model switch failed: %s", err)
            if err is not None:  # None: nothing the user can act on (set_thinking_level)
                _toast(err, title)
            # The refusal may mean the key changed elsewhere (removed from
            # another device, a Codex sign-in gone): re-read so the island
            # follows.
            credential_state.refresh()
            preference_state.refresh()
    except Exception as e:  # noqa: BLE001 — a callback must never raise into a timer
        logger.error("BYOK switch callback failed: %s", e, exc_info=True)
    _redraw()


def _toast(err, title=SWITCH_TITLE) -> None:
    try:
        from mixar.modules.common.notifications import get_notification_store

        # One stable id: a second failed pick replaces the toast.
        get_notification_store().push(
            "error", title, body=err or n_("Please try again."),
            ttl_ms=8000, id=SWITCH_TOAST_ID,
        )
    except Exception:  # noqa: BLE001 — the log line already records it
        pass


def _redraw() -> None:
    try:
        from mixar.modules.common.utils.platform_utils import trigger_ui_redraw

        trigger_ui_redraw()
    except Exception as exc:  # noqa: BLE001
        logger.debug("BYOK switch redraw failed: %s", exc)


#: No operators: the island card's key rows run `mixar.agent_pick`.
classes = ()
