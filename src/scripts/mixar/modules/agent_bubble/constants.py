# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent Bubble constants."""

import sys


# Platforms whose GHOST layer implements the ``Mixar_Window*`` helpers that the
# native window-state operators are built on. Those helpers exist in exactly
# two places — ``GHOST_SystemCocoa.mm`` and ``GHOST_SystemWin32.cc`` — and
# there is no X11 implementation, so on Linux the bodies of
# ``mixar_bubble_{minimise,restore,toggle_expand}_exec`` (space_agent_bubble.cc,
# all three guarded by ``#if defined(__APPLE__) || defined(_WIN32)``) compile
# down to a bare ``return OPERATOR_CANCELLED``.
#
# Every call site sits inside that guard, so Linux never references the missing
# symbols and the build links cleanly — there is no compile-time signal. The
# operators simply do nothing, silently, which reads to the user as frozen UI
# rather than as a feature that isn't there yet.
#
# This is an ALLOWLIST, deliberately not ``!= "win32"``. A platform earns these
# controls by having someone write its window helpers; anything else stays
# opted out and inherits no dead buttons.
BUBBLE_WINDOW_CONTROLS_SUPPORTED = sys.platform in {"darwin", "win32"}
