# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Save or clear the hosted agent-model pick (the island card's Mixie rows,
through `agent_pick_ops`).

Both write OPTIMISTICALLY: the WindowManager mirror flips on the click, the
HTTP request follows on a worker thread, and a non-2xx response puts the
previous value back. A row that visibly does nothing for half a second
reads as a swallowed click. Send and further model changes stay disabled until
the write finishes: the server resolves the stored preference at turn start,
so an optimistic label alone is not sufficient to safely send.

Threading: the request runs on a daemon thread inside `preference_client` and
the callback is marshalled back through `bpy.app.timers`, so nothing here
touches `bpy` off the main thread. The click's operator is long gone by then,
so failures surface as a toast.
"""

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_

from ...core import preference_client, preference_state

logger = get_logger(__name__)


def _notify_failure(title: str, message: str) -> None:
    """Surface a server-side rejection. Best-effort; never raises."""
    try:
        from mixar.modules.common.notifications import get_notification_store

        get_notification_store().push("error", title, body=message or "")
    except Exception as exc:  # noqa: BLE001 — a toast must not break a save
        logger.debug("Agent model picker toast failed: %s", exc)


def _redraw() -> None:
    try:
        from mixar.modules.common.utils.platform_utils import trigger_ui_redraw

        trigger_ui_redraw()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Agent model picker redraw failed: %s", exc)


def set_hosted(wm, provider: str, model: str, thinking: str = "", label: str = "") -> bool:
    """Save the hosted pick (optimistic mirror, PUT on a worker). False when
    another pick is in flight. Run by the island popup's `mixar.agent_pick`,
    directly or after a pause when a key was in use."""
    if not preference_state.begin_mutation():
        return False
    epoch = preference_state.current_epoch()
    previous = preference_state.snapshot()
    if not label:
        from ...core import catalog_labels
        label = catalog_labels.lookup_model_label(provider, model)
    preference_state.apply_local(
        {
            "mixar_agent_model_provider": provider,
            "mixar_agent_model_id": model,
            "mixar_agent_model_label": label or model,
            "mixar_agent_model_thinking": thinking,
            # A row the user could click was drawn eligible; the server has
            # the last word and a 400 reverts this wholesale.
            "mixar_agent_model_eligible": True,
        },
        wm,
        epoch=epoch,
    )
    _redraw()

    def _done(success, data, err):
        _on_save_done(epoch, previous, success, data, err)

    preference_client.save_preference(
        provider=provider,
        model=model,
        on_done=_done,
        thinking_level=thinking or None,
    )
    return True


def reset_hosted(wm) -> bool:
    """Clear the hosted pick (the server default). False when a pick is in flight."""
    if not preference_state.begin_mutation():
        return False
    epoch = preference_state.current_epoch()
    previous = preference_state.snapshot()
    preference_state.apply_local(
        {
            "mixar_agent_model_provider": "",
            "mixar_agent_model_id": "",
            "mixar_agent_model_label": "",
            "mixar_agent_model_thinking": "",
            "mixar_agent_model_eligible": True,
        },
        wm,
        epoch=epoch,
    )
    _redraw()

    def _done(success, data, err):
        _on_reset_done(epoch, previous, success, err)

    preference_client.delete_preference(on_done=_done)
    return True


# ---------------------------------------------------------------------------
# Main-thread callbacks
# ---------------------------------------------------------------------------

def _on_save_done(epoch, previous, success, data, err) -> None:
    """Adopt the server's echo, or put the previous pick back.

    ``epoch`` is captured before the request: a logout in between makes both
    branches a no-op, because restoring the logged-out account's model in front
    of the next user is worse than leaving the cleared default.
    """
    if epoch != preference_state.current_epoch():
        return
    if success:
        # The PUT echoes the authoritative state (including a thinking level
        # the server normalised); a follow-up GET would race it.
        if isinstance(data, dict) and data.get("items"):
            preference_state.apply_from_payload(data, epoch=epoch)
        elif isinstance(data, dict) and data.get("model"):
            # PUT returns one role view; GET returns an items envelope.
            preference_state.apply_from_payload({
                "items": [data],
                "byok_active": previous["mixar_agent_model_byok_active"],
            }, epoch=epoch)
        else:
            preference_state.end_mutation(epoch)
            preference_state.refresh()
    else:
        logger.debug("Agent model save rejected, reverting: %s", err)
        preference_state.apply_local(previous, epoch=epoch)
        # The server's message is user-safe per the contract ("Model not
        # available: ..."), and a transport failure already arrives carrying a
        # NET-* support code from `classify_network_error`. Surface it verbatim.
        _notify_failure(n_("Could not change model"), err or "")
    preference_state.end_mutation(epoch)
    _redraw()


def _on_reset_done(epoch, previous, success, err) -> None:
    if epoch != preference_state.current_epoch():
        return
    if success:
        preference_state.end_mutation(epoch)
        preference_state.refresh()
    else:
        logger.debug("Agent model reset rejected, reverting: %s", err)
        preference_state.apply_local(previous, epoch=epoch)
        _notify_failure(n_("Could not reset model"), err or "")
    preference_state.end_mutation(epoch)
    _redraw()


#: No operators: the island card's rows run `mixar.agent_pick`.
classes = ()
