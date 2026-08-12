# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Privacy-safe import telemetry."""

from __future__ import annotations

from .capture import capture
from .constants import EVENT_IMPORT_INITIATED


def capture_import_initiated(context, import_format: str) -> None:
    """Capture a File-menu import start without paths or import settings."""
    capture(EVENT_IMPORT_INITIATED, {
        "format": str(import_format),
        "via": "file_menu",
    }, context=context)
