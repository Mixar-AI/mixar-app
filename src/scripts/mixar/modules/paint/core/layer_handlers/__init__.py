# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer type handlers for different layer behaviors.

This module provides handler classes for Fill, Paint, and Procedural layers,
each encapsulating type-specific behavior for channel setup, UI drawing, etc.
"""

from .handler_registry import get_handler, register_handler
from .base_handler import LayerTypeHandler

__all__ = [
    'get_handler',
    'register_handler',
    'LayerTypeHandler',
]
