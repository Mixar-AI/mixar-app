# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded local UI protocol; shared by MCP and the development harness."""

CAPABILITY = "mixar_ui_v1"
MAX_PENDING = 32
MAX_TARGETS = 200
MAX_IMAGE_BYTES = 4 * 1024 * 1024
ACTION_TIMEOUT = 10.0
CONTEXT_TTL = 30.0
MAX_CONTEXTS = 32


class UIError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code

    def result(self):
        return {"error_type": self.code, "error": str(self)}
