# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Stable, path-free errors returned by the context-folder RPC."""

import traceback


class ContextFolderError(Exception):
    """Expected failure with a stable public code and a path-free message."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def public_error(exc: Exception) -> dict:
    """An RPC error body. Unexpected exceptions may carry the local root (an
    ``OSError`` names its file), so only their class reaches the wire; the
    detail is printed to the local console for diagnosis."""
    if isinstance(exc, ContextFolderError):
        return {"success": False, "error": {"code": exc.code, "message": exc.message}}
    print("[ContextFolder] Unexpected failure:", "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    ))
    return {"success": False, "error": {
        "code": "internal_error",
        "message": "The local folder operation failed",
    }}
