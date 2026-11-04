# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Crash-safe sessions: save points, the restore offer, agent continuity.

``journal``, ``decision``, ``scheduler`` and ``jobs`` are plain Python;
``runtime`` is the bpy half, loaded by ``bootstrap/session_recovery_module``.
"""
