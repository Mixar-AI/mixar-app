# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent Bubble constants."""

import sys


# Platforms whose GHOST layer implements the ``Mixar_Window*`` helpers that the
# native window-state operators are built on. Those helpers exist in
# ``GHOST_SystemCocoa.mm``, ``GHOST_SystemWin32.cc`` and ``GHOST_MixarX11.cc``.
# Every call site in space_agent_bubble.cc is inside
# ``#if defined(__APPLE__) || defined(_WIN32) || defined(__linux__)``, so a
# platform without a backend compiles the operator bodies down to a bare
# ``return OPERATOR_CANCELLED``.
#
# On Linux the helpers are Xlib/EWMH-backed (MWM decorations, transient-for
# parenting, ``_NET_WM_MOVERESIZE`` drags). They resolve through a
# ``dynamic_cast`` to the X11 classes, so under Wayland — where GHOST picks a
# different backend at run time — they are safe no-ops rather than crashes.
#
# This is an ALLOWLIST, deliberately not ``!= "win32"``. A platform earns these
# controls by having someone write its window helpers; anything else stays
# opted out and inherits no dead buttons.
BUBBLE_WINDOW_CONTROLS_SUPPORTED = sys.platform in {"darwin", "win32", "linux"}

# How far (window pixels) a press on the pill window may travel and still be
# a CLICK. Past it the press becomes a DRAG that moves the pill. The pill's
# press is decided by how it ends, never at PRESS time — see
# ui/operators/bubble_header_drag_op.py.
PILL_DRAG_THRESHOLD_PX = 4
