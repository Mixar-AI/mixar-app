# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Privacy-bounded first-party product analytics."""

from .capture import capture, instrument_operator_classes, shutdown

__all__ = ("capture", "instrument_operator_classes", "shutdown")
