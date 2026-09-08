# SPDX-License-Identifier: GPL-3.0-or-later
"""Path-sanitized script receipts and native rollback status."""

from dataclasses import dataclass, field
from typing import Any

from .sandbox_builtins import sanitize_value


@dataclass
class ExecutionResult:
    """Result of script execution."""

    success: bool
    output: str = ""
    error: str | None = None
    traceback: str | None = None

    # Changes detected
    created_objects: list[str] = field(default_factory=list)
    modified_objects: list[str] = field(default_factory=list)
    deleted_objects: list[str] = field(default_factory=list)

    # Return value if script returned something
    return_value: Any = None
    rollback: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON-RPC response.

        Returns a response with `success` at the top level.
        If __RESULT__ was set in the script and is a dict, its contents
        are flattened into the response.
        """
        response = {
            "success": self.success,
        }

        # Flatten return_value dict into response (for __RESULT__ data)
        if self.return_value and isinstance(self.return_value, dict):
            sanitized = sanitize_value(self.return_value)
            if isinstance(sanitized, dict):
                response.update(sanitized)
        elif self.return_value is not None:
            response["return_value"] = sanitize_value(self.return_value)

        response["success"] = (
            self.success and response.get("success", True) is not False
        )
        if self.rollback:
            response["rollback"] = self.rollback
        # Include metadata only if present
        if self.output:
            response["output"] = self.output
        if self.created_objects:
            response["created_objects"] = self.created_objects
        if self.modified_objects:
            response["modified_objects"] = self.modified_objects
        if self.deleted_objects:
            response["deleted_objects"] = self.deleted_objects
        if self.error:
            response["error"] = self.error
        # Forward the traceback over the (internal) RPC so the backend can log the
        # failing line. This is an internal channel; the backend strips tracebacks
        # from any client-facing API response per its own contract.
        if self.traceback:
            response["traceback"] = self.traceback

        return response
