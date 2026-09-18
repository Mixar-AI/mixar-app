# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Refine / Revert row under a sidebar prompt field.

Drawing only. It lives beside ``sidebar_ui_helpers`` rather than inside it
purely for the 500-line rule — ``draw_prompt_section`` is its one caller, so
every tab prompt gets the row by construction.

The canvas node's equivalent is painted in C++
(``mixie_draw_moodboard_node_tile_controls.cc``); both drive the same two
operators and the same engine in ``core.prompt_refine``.
"""


def draw_prompt_refine_row(layout, prop_owner):
    """Refine / Revert under a prompt field, for a known refinable tab.

    Draws nothing for an owner with no entry in
    ``core.prompt_refine_targets.SIDEBAR_PROMPT_TARGETS`` — the feature never
    guesses what a prompt is for, because refining an image prompt as if it
    were a video prompt is worse than not refining at all.

    Refine is disabled on an empty prompt (there is nothing to improve) and
    while a refinement is in flight. Once one has landed, Revert joins it in
    the same row rather than replacing it: a rewrite the user does not like
    is as often answered by "try again" as by "give me mine back", and
    Revert is still the only thing that puts their own wording back.
    """
    try:
        from mixar.modules.moodboard.core import prompt_refine
        from mixar.modules.moodboard.core.prompt_refine_targets import (
            SIDEBAR_PROMPT_TARGETS,
            owner_type_of,
        )
    except Exception:
        return

    owner_type = owner_type_of(prop_owner)
    if owner_type not in SIDEBAR_PROMPT_TARGETS:
        return

    refining = prompt_refine.sidebar_is_refining(prop_owner, owner_type)
    can_revert = prompt_refine.sidebar_can_revert(prop_owner, owner_type)

    row = layout.row(align=True)

    # Each button gets its own sub-row: `enabled` applies to a whole layout
    # item, so sharing one row would grey out Revert whenever Refine is
    # unavailable — and a Revert you cannot press is the one affordance that
    # must never be taken away once a rewrite has landed.
    refine_row = row.row(align=True)
    refine_row.enabled = (
        bool(getattr(prop_owner, "prompt", "").strip()) and not refining
    )
    op = refine_row.operator(
        "mixie.refine_prompt",
        text="Refining..." if refining else "Refine",
        icon='SHADERFX',
    )
    op.owner = owner_type

    if can_revert:
        op = row.operator("mixie.revert_prompt", text="Revert", icon='LOOP_BACK')
        op.owner = owner_type
