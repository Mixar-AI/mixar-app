# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicitly expand the sketch pill when a scenario needs full controls."""


def open_controls(qa):
    qa.wait("bool(drv.find(surface='pill_draft_preview'))", timeout=10)
    qa.click(surface='pill_cat')
    qa.wait("bool(drv.find(op='MIXAR_OT_scribble_toggle'))", timeout=10)
