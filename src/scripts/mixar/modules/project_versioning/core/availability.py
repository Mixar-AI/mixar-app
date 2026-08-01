# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cheap Lore capability detection that never imports the native SDK."""

import importlib.util
import platform
import sys

from .models import Availability


def detect(*, build_enabled: bool) -> Availability:
    if not build_enabled:
        return Availability.BUILD_DISABLED

    machine = platform.machine().lower()
    if sys.platform == "darwin" and machine not in {"arm64", "aarch64"}:
        return Availability.UNSUPPORTED_PLATFORM
    if sys.platform == "win32" and machine not in {"amd64", "x86_64"}:
        return Availability.UNSUPPORTED_PLATFORM
    if sys.platform.startswith("linux"):
        libc_name, libc_version = platform.libc_ver()
        if libc_name == "glibc":
            parts = tuple(int(part) for part in libc_version.split(".")[:2] if part.isdigit())
            if parts and parts < (2, 39):
                return Availability.UNSUPPORTED_PLATFORM

    return (
        Availability.AVAILABLE
        if importlib.util.find_spec("lore") is not None
        else Availability.SDK_MISSING
    )
