# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Toggle semantics for the Zen Mode Move / Rotate / Scale strip.

The stock toolbar buttons PERSIST: ``wm.tool_set_by_id`` activates a tool and
Blender never has "no tool" — exactly one tool is always active for the
workspace. Zen's strip is only three buttons, so a click on the one that is
already active has to land somewhere else, and the answer is "back where you
came from": the tool that was active before the strip was used (Select Box,
Tweak, a brush, whatever it was), falling back to the toolbar's own
``tool_fallback_id`` when there is nothing to restore — a transform tool
reached from a keymap, a fresh viewport, a file that was just opened.

Only NON-transform tools are remembered, so Move → Rotate → click Rotate
returns to the user's select tool rather than ping-ponging between the two
transform tools. Every click that lands on the active button therefore has
the same, predictable way out of the strip.

Why the choice is made at DRAW time instead of in an operator of our own:
Blender decides that a button IS a toolbar tool button by matching its
operator against ``WM_OT_tool_set_by_id`` **by pointer** (``but_is_tool`` in
``interface_query.cc``, which calls its own approach "very evil!"), and that
single test selects the toolbar widget style, the toolbar icon size, the
tool-icon desaturation and Mixar's own toolbar SVG scaling. Point the button
at any other operator and the strip draws as three plain buttons. So the
strip keeps the stock operator and only the ``name`` it carries — which tool
to activate — is decided here.

The flip side of having no operator of ours is that nothing runs on a click
to record the tool being displaced, so the memory is fed from the strip's own
draw instead. That is the better source anyway: it follows tool changes made
anywhere (a keymap, a brush picked in another mode), not just clicks on this
strip.

The remembered tool is one slot for the whole session rather than one per
area: Blender stores the active tool on the WORKSPACE (the writable
``WorkSpaceTool.idname``), not per viewport, so two viewports in Zen Mode
share a single tool anyway and a per-area cache would model something that
is not per-area.
"""

from ...constants import ZEN_TRANSFORM_TOOL_IDS

#: The last non-transform tool seen active, or None.
_previous_tool_idname = None


def previous_tool_idname():
    """The tool the strip returns to when its active button is clicked."""
    return _previous_tool_idname


def note_active_tool(active_idname):
    """File ``active_idname`` away as the tool the strip came from.

    Called from the strip's draw with whatever tool is active. Only a
    non-transform tool is worth remembering: Move being active must not
    overwrite the select tool the user actually came from.
    """
    global _previous_tool_idname
    if active_idname and active_idname not in ZEN_TRANSFORM_TOOL_IDS:
        _previous_tool_idname = active_idname


def toggle_target(clicked_idname, active_idname, fallback_idname, is_available=None):
    """Which tool a click on ``clicked_idname`` must activate.

    Reads the one remembered slot and is otherwise pure, so the
    decide-then-set contract can be pinned without a live Blender.

    ``is_available`` is an optional predicate on a tool idname, used to
    reject a remembered tool that no longer exists in the current mode (say
    a brush idname after leaving paint mode): activating it would return
    ``{'CANCELLED'}`` and leave the button looking dead, so the fallback is
    taken instead.
    """
    if clicked_idname != active_idname:
        return clicked_idname
    previous = _previous_tool_idname
    if previous and previous not in ZEN_TRANSFORM_TOOL_IDS:
        if is_available is None or is_available(previous):
            return previous
    return fallback_idname


classes = ()
