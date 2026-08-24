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
    try:
        from mixar.modules.common.job_queue.core.generate_cost import (
            reset_estimate_state,
        )
        reset_estimate_state()
    except Exception as e:
        logger.warning(f"Generate-cost estimate clear failed: {e}")


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
