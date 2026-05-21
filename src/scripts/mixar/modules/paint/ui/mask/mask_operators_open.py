# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Open image/data as mask operators.

This module re-exports operators for opening images and available data as layer masks.
The actual implementations are split into separate modules for maintainability.
"""

# Re-export operators for backward compatibility
from .mask_operators_open_image import MOpenImageAsMask
from .mask_operators_open_data import MOpenAvailableDataAsMask

__all__ = ["MOpenImageAsMask", "MOpenAvailableDataAsMask"]
