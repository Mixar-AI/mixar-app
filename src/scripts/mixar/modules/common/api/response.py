# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
API Response Wrapper

Provides a standardized response container for API responses.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class APIResponse:
    """
    Standardized API response container.

    Attributes:
        success: Whether the request was successful
        status_code: HTTP status code
        data: Response payload (parsed JSON or raw content)
        message: Human-readable status message
        headers: Response headers
        raw: Raw response object for advanced use cases
    """

    success: bool
    status_code: int
    data: Any = None
    message: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    raw: Optional[Any] = None

    @classmethod
    def from_success(
        cls,
        status_code: int,
        data: Any = None,
        message: str = "Success",
        headers: Optional[Dict[str, str]] = None,
    ) -> "APIResponse":
        """Create a successful response."""
        return cls(
            success=True,
            status_code=status_code,
            data=data,
            message=message,
            headers=headers or {},
        )

    @classmethod
    def from_error(
        cls,
        status_code: int,
        message: str,
        data: Any = None,
    ) -> "APIResponse":
        """Create an error response."""
        return cls(
            success=False,
            status_code=status_code,
            data=data,
            message=message,
        )
