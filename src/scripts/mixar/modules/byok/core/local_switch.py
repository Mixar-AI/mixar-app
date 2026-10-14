# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Tear down the managed local runtime when the credential set leaves it.

Shared by the dialog's save/remove callbacks (`ui/operators/byok_ops.py`)
and the chat card's "Use Mixar credits instead" removal
(`space_mixie_chat/core/byok_card.py`). Main thread.
"""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def deregister_local_if_switched_away(active_provider) -> None:
    """The credential set now points at ``active_provider`` (None = removed).
    If a managed local registration is still on disk, tear it down — the
    backend will never relay to it again, so keeping llama-server running
    (and resurrecting it every startup) would waste the user's RAM."""
    try:
        from ..constants import LOCAL_PROVIDER_ID
        if active_provider == LOCAL_PROVIDER_ID:
            return
        from mixar.modules.local_models.core import manifest, orchestrator
        if manifest.get_registered() is None:
            return
        logger.info("BYOK switched off local — deregistering local runtime")
        orchestrator.deregister()
    except Exception as e:  # noqa: BLE001 — never block the credential change
        logger.warning("Local deregistration skipped: %s", e)
