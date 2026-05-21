# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bake settings management and restoration - main module

This module provides backward compatibility by re-exporting functions from
the refactored submodules:
- bake_state_manager: State saving and restoration (remember/recover)
- bake_prepare: Bake preparation logic
- composite_settings: Compositor settings management
"""

# Re-export all public functions for backward compatibility
from .bake_state_manager import (
    EMPTY_IMG_NODE,
    remember_before_bake,
    recover_bake_settings,
)

from .bake_prepare import prepare_bake_settings

from .composite_settings import (
    prepare_composite_settings,
    recover_composite_settings,
)

# Export all public symbols
__all__ = [
    "EMPTY_IMG_NODE",
    "remember_before_bake",
    "recover_bake_settings",
    "prepare_bake_settings",
    "prepare_composite_settings",
    "recover_composite_settings",
]
