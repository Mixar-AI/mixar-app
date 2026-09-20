# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Transport-independent chat payload consumed by the existing slot renderer."""
from dataclasses import dataclass


@dataclass
class AgentEvent:
    event_type: str
    data: dict
