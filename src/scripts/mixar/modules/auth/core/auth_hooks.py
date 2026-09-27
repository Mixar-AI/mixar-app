# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Authentication lifecycle hooks.

Functions that should run after successful login/token refresh or
on logout, such as refreshing or clearing generation config caches.
"""

from ....config.logging_config import get_logger

logger = get_logger(__name__)


def refresh_generation_caches():
    """Refresh the generation catalog cache after successful authentication.

    The legacy per-feature imagegen / model_3d caches were retired — the
    unified generation catalog is the single source for models, styles
    and parameter schemas.
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            refresh_generation_catalog_cache,
        )
        refresh_generation_catalog_cache()
    except Exception as e:
        logger.warning(f"Generation catalog refresh failed: {e}")
    try:
        from mixar.bootstrap.chat_generate_options_cache import (
            refresh_chat_generate_options_cache,
        )
        refresh_chat_generate_options_cache()
    except Exception as e:
        logger.warning(f"Chat generate options refresh failed: {e}")


def invalidate_generation_caches():
    """Clear the generation catalog + chat options caches on logout."""
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            clear_generation_catalog_cache,
        )
        clear_generation_catalog_cache()
    except Exception as e:
        logger.warning(f"Generation catalog clear failed: {e}")
    try:
        from mixar.bootstrap.chat_generate_options_cache import (
            clear_chat_generate_options_cache,
        )
        clear_chat_generate_options_cache()
    except Exception as e:
        logger.warning(f"Chat generate options clear failed: {e}")


def maybe_show_onboarding(email: str) -> None:
    """Trigger the onboarding tour for ``email`` if they haven't
    completed or skipped it before on this machine.

    Called from every successful auth path (startup token-validation
    AND fresh SSO login). The seen-list dedupes — same email won't
    see the tour twice.
    """
    if not email:
        return
    try:
        from mixar.modules.onboarding.core import maybe_show_for_user
        maybe_show_for_user(email)
    except Exception as exc:
        logger.warning(f"Onboarding hook failed: {exc}")


def refresh_agent_settings():
    """Refresh BYOK credential state + the provider/model catalog after auth.

    Kept separate from `refresh_generation_caches` on purpose: agent settings
    and the generation catalog have independent failure domains and independent
    owners, and folding them together would make a generation-catalog test fail
    for a BYOK reason.

    Both fetches are plain HTTP, so this is the whole trigger — there is no
    socket to wait for. That is the point of the transport: the credential fetch
    used to ride the agent WebSocket and lost the race against its own connect
    on every cold start.
    """
    try:
        from mixar.modules.byok.core import credential_state

        credential_state.refresh()
    except Exception as e:
        logger.warning(f"BYOK state refresh failed: {e}")
    try:
        from mixar.modules.byok.core import models_cache

        models_cache.refresh()
    except Exception as e:
        logger.warning(f"Agent models catalog refresh failed: {e}")
    try:
        from mixar.modules.byok.core import preference_state

        preference_state.refresh()
    except Exception as e:
        logger.warning(f"Agent model preference refresh failed: {e}")


def invalidate_agent_settings():
    """Clear BYOK state, the catalog (memory and disk) and the model pick.

    The SINGLE owner of all three on logout. Clearing any of them from a second
    place gives a worker still in flight two orderings to win in — see the note
    in `space_mixie_chat/ui/operators/auth_ops.py`.
    """
    try:
        from mixar.modules.byok.core import credential_state

        credential_state.clear()
    except Exception as e:
        logger.warning(f"BYOK state clear failed: {e}")
    try:
        from mixar.modules.byok.core import models_cache

        models_cache.clear()
    except Exception as e:
        logger.warning(f"Agent models catalog clear failed: {e}")
    try:
        from mixar.modules.byok.core import preference_state

        preference_state.clear()
    except Exception as e:
        logger.warning(f"Agent model preference clear failed: {e}")
