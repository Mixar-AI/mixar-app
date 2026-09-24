# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Project the Virtual Camera session onto the WindowManager mirror.

The pairing UI is the Cinema surface's phone hand-off button and its pairing
card — custom-drawn C++ that reads RNA, not Python singletons. This module is
the ONLY writer of ``wm.mixar_virtual_camera_*``
(``ui/properties/virtual_camera_props.py`` declares them).

Two rules, both load-bearing:

* **Main thread only.** Called from the runtime's ``bpy.app.timers`` pump and
  from the lifecycle operators — never from a server thread, and never from a
  draw callback (an RNA write there is the handler-pattern violation
  CLAUDE.md bans).
* **Write on change only.** ``sync()`` returns True when something moved, so
  the caller redraws exactly then; the QR is re-encoded only when the URL
  itself changes, because encoding is the expensive part and the URL only
  moves on start and on re-pairing.
"""

from __future__ import annotations

import bpy

from mixar.config.logging_config import get_logger

from ..constants import QR_MATRIX_MAXLEN
from . import qr_encoder

logger = get_logger(__name__)

#: Last URL encoded, so a 30 Hz pump never re-encodes a QR that did not move.
_encoded_url: str | None = None
_encoded_matrix: tuple[str, int] = ("", 0)


def qr_modules(url: str) -> tuple[str, int]:
    """Row-major ``'0'``/``'1'`` modules for *url*, and the side length.

    ``("", 0)`` when the URL is empty or the encoder refuses it — the card
    then shows the link text alone rather than a broken code.
    """
    global _encoded_url, _encoded_matrix
    if url == _encoded_url:
        return _encoded_matrix
    _encoded_url = url
    if not url:
        _encoded_matrix = ("", 0)
        return _encoded_matrix
    try:
        matrix = qr_encoder.encode(url)
        size = len(matrix)
        flat = "".join("1" if cell else "0" for row in matrix for cell in row)
        if size <= 0 or len(flat) > QR_MATRIX_MAXLEN:
            raise ValueError(f"QR matrix too large to mirror: {size}x{size}")
        _encoded_matrix = (flat, size)
    except Exception as exc:  # noqa: BLE001 — a missing QR is not a dead feature
        logger.warning("virtual_camera: QR encoding failed: %s", exc)
        _encoded_matrix = ("", 0)
    return _encoded_matrix


def _notice(runtime) -> str:
    """The one thing worth saying went wrong, most specific first."""
    return runtime.server.state.last_error or runtime.last_error or ""


def sync(runtime) -> bool:
    """Push *runtime*'s state onto the mirror. True when anything changed."""
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return False
    state = runtime.server.state
    url = state.url if state.running else ""
    flat, size = qr_modules(url if not state.phone_connected else "")
    values = {
        "mixar_virtual_camera_running": bool(state.running),
        "mixar_virtual_camera_connected": bool(state.phone_connected),
        "mixar_virtual_camera_tls": bool(state.tls),
        "mixar_virtual_camera_url": url,
        "mixar_virtual_camera_notice": _notice(runtime),
        "mixar_virtual_camera_qr": flat,
        "mixar_virtual_camera_qr_size": size,
    }
    changed = False
    for name, value in values.items():
        try:
            if getattr(wm, name) != value:
                setattr(wm, name, value)
                changed = True
        except AttributeError:
            # Properties not registered yet (or already unregistered): the
            # surface simply has nothing to read.
            return changed
    return changed


def clear() -> None:
    """Blank the mirror — the surface must never show a dead pairing code."""
    global _encoded_url, _encoded_matrix
    _encoded_url = None
    _encoded_matrix = ("", 0)
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return
    for name, value in (
        ("mixar_virtual_camera_running", False),
        ("mixar_virtual_camera_connected", False),
        ("mixar_virtual_camera_tls", False),
        ("mixar_virtual_camera_url", ""),
        ("mixar_virtual_camera_notice", ""),
        ("mixar_virtual_camera_qr", ""),
        ("mixar_virtual_camera_qr_size", 0),
    ):
        try:
            setattr(wm, name, value)
        except AttributeError:
            return
