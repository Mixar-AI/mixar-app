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
    """Refresh generation config caches after successful authentication."""
    try:
        from mixar.bootstrap.imagegen_cache import refresh_imagegen_cache
        refresh_imagegen_cache()
    except Exception as e:
        logger.warning(f"ImageGen cache refresh failed: {e}")
    try:
        from mixar.bootstrap.model_3d_cache import refresh_models_cache
        refresh_models_cache()
    except Exception as e:
        logger.warning(f"Model3D cache refresh failed: {e}")


def invalidate_generation_caches():
    """Clear generation config caches on logout."""
    try:
        from mixar.bootstrap.imagegen_cache import clear_imagegen_cache
        clear_imagegen_cache()
    except Exception as e:
        logger.warning(f"ImageGen cache clear failed: {e}")
    try:
        from mixar.bootstrap.model_3d_cache import clear_models_cache
        clear_models_cache()
    except Exception as e:
        logger.warning(f"Model3D cache clear failed: {e}")


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
