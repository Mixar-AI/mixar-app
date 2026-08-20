# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Stable, path-free errors returned by the project RPC."""


class AddonProjectError(Exception):
    """Expected project operation failure with a stable public code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def public_error(exc: Exception, project_root=None) -> dict:
    """Convert an exception to a response without leaking a local root path."""
    if isinstance(exc, AddonProjectError):
        code = exc.code
        message = exc.message
    else:
        code = "internal_error"
        # Unexpected OS/import errors may contain the project root, the local
        # Mixar install path, or the client-state directory. Keep those details
        # on the Blender client instead of returning them over JSON-RPC.
        message = "The local add-on project operation failed"
    if project_root is not None:
        root = str(project_root)
        message = message.replace(root, "<project>")
        message = message.replace(root.replace("/", "\\"), "<project>")
    return {"success": False, "error": {"code": code, "message": message}}
