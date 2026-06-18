# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Core logic for the operation_history module (no UI)."""

from .store import record_operation  # noqa: F401  public emit API
