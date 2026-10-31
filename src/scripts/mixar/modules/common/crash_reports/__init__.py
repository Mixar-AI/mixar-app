# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Crash reporting: crash files from earlier sessions and uncaught Python
exceptions, scrubbed and sent to the backend when the user consents and is
signed in (docs/modules/crash-handling.md). Started by
``bootstrap/crash_reports_module.py``."""

from .core.excepthook import report_exception

__all__ = ("report_exception",)
