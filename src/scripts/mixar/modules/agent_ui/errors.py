# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Typed failure for agent UI control — carries a closed-set wire code."""

from .constants import ERR_INTERNAL


class UIControlError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code or ERR_INTERNAL
        self.message = message or code

    def to_result(self) -> dict:
        return {"success": False, "error": {"code": self.code, "message": self.message}}
