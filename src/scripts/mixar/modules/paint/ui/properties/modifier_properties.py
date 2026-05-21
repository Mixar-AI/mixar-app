# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Re-export MPaintModifier from canonical location for backward compatibility.

NOTE: No classes tuple here - registration is handled by the canonical location
at ui/modifier/modifier_properties.py. This file only provides import compatibility.
"""

# Re-export from canonical location
from ..modifier.modifier_properties import MPaintModifier

__all__ = ["MPaintModifier"]
