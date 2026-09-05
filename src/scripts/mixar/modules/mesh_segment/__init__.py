# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mesh Segment Module.

Provides UV mesh segmentation functionality with API integration.
"""

from .core import apply_labels_to_mesh

__all__ = [
    "apply_labels_to_mesh",
]
