# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""The Assemble card's settings popup: one row set per connected part.

Draw code only. It reads the rows ``assemble_schema`` minted and the last
run's report, and never writes scene data: rows that are missing simply are
not drawn until the next schema sync adds them.
"""

from ..core.assemble_constants import (
    FLOAT_SLOTS,
    FOREARM_SLOTS,
    HAND_SLOTS,
    HEAD_SLOTS,
    SLOT_CHOICES,
    param_name,
)
from ..core.assemble_schema import (
    assemble_summary,
    body_link,
    last_outcome,
    part_label,
    part_links,
)
from .sidebar_ui_helpers import (
    draw_dropdown,
    draw_hint,
    draw_section_box,
    draw_toggle,
)

_SLOT_LABELS = dict(SLOT_CHOICES)
# Where a part is still AUTO and no run has resolved it yet, every control
# it might need stays on screen rather than hiding one it turns out to use.
_UNRESOLVED = "AUTO"


def _socket_index(socket_id: str) -> int:
    try:
        return int(str(socket_id).partition(":")[2])
    except ValueError:
        return -1


def _effective_slot(slot_row, outcome: dict) -> str:
    """The explicit slot, else what the last run resolved AUTO to."""
    value = str(getattr(slot_row, "value_enum", "") or _UNRESOLVED)
    if value != _UNRESOLVED:
        return value
    resolved = outcome.get("slot")
    return resolved if isinstance(resolved, str) and resolved else _UNRESOLVED


def outcome_text(part: dict) -> str:
    """One line for a part's last result, e.g. ``→ mixamorig:RightHand · 0.93 m (52%)``."""
    notes = [str(note) for note in part.get("notes") or () if note]
    if part.get("status") == "skipped":
        return f"skipped: {notes[0]}" if notes else "skipped"
    slot = str(part.get("slot") or "")
    bone = str(part.get("bone") or "")
    if bone and part.get("bone_how") != "estimated":
        text = f"→ {bone}"
        size_m, size_pct = part.get("size_m"), part.get("size_pct")
        if isinstance(size_m, (int, float)) and isinstance(size_pct, (int, float)):
            text += f" · {size_m:.2f} m ({size_pct:.0f}%)"
    else:
        missing = "hand bone" if slot in HAND_SLOTS | FLOAT_SLOTS else "bone"
        text = f"→ {_SLOT_LABELS.get(slot, slot or 'Body')} (estimated, no {missing} found)"
    if part.get("slot_guessed"):
        text += " (guessed)"
    return text


def _draw_outcome(col, part: dict) -> None:
    if not part:
        return
    draw_hint(col, outcome_text(part),
              icon='INFO' if part.get("status") == "skipped" else 'CHECKMARK')
    if part.get("status") != "skipped":
        notes = [str(note) for note in part.get("notes") or () if note]
        if notes:
            draw_hint(col, "; ".join(notes))


def _draw_part(layout, scene, link, rows: dict, outcomes: dict) -> None:
    index = _socket_index(link.to_socket)
    title = part_label(scene, link.from_node_id) or f"Part {index + 1}"
    col = draw_section_box(layout, title, icon='OBJECT_DATA')
    slot_row = rows.get(param_name("slot", index))
    if slot_row is None:
        col.label(text="Settings appear after the card refreshes", icon='INFO')
        return
    outcome = outcomes.get(link.to_socket) or {}
    slot = _effective_slot(slot_row, outcome)

    col.label(text="Slot")
    draw_dropdown(col, slot_row, 'value_enum', text="")
    hold_row = rows.get(param_name("hold", index))
    if hold_row is not None and slot in HAND_SLOTS | FOREARM_SLOTS | {_UNRESOLVED}:
        col.label(text="Hold")
        draw_dropdown(col, hold_row, 'value_enum', text="")
    size_row = rows.get(param_name("size", index))
    if size_row is not None:
        basis = "head width" if slot in HEAD_SLOTS else "height"
        col.label(text=f"Size (% of {basis}, 0 = auto)")
        field = col.row(align=True)
        field.prop(size_row, 'value_float', text="")
        if hasattr(field, 'mixar_style'):
            field.mixar_style(component='NUMBER')
    flip_row = rows.get(param_name("flip", index))
    if flip_row is not None and slot in HAND_SLOTS | {_UNRESOLVED}:
        draw_toggle(col.row(), flip_row, 'value_boolean', text="Flip edge")
    _draw_outcome(col, outcome)


def draw_assemble_node(layout, scene, node) -> None:
    """Body, part rows, pipeline hints, then Assemble and Reset."""
    body = body_link(scene, node)
    if body is not None:
        name = part_label(scene, body.from_node_id) or "connected"
        layout.label(text=f"Body: {name}", icon='ARMATURE_DATA')
    else:
        layout.label(text="Connect a rigged body", icon='INFO')

    rows = {parameter.name: parameter for parameter in node.parameters}
    outcomes = last_outcome(node)
    links = [link for link in part_links(scene, node) if _socket_index(link.to_socket) >= 0]
    for link in links:
        _draw_part(layout, scene, link, rows, outcomes)
    if not links:
        draw_hint(layout, "Connect each part's 3D card to a Part input", icon='INFO')

    hints = layout.column()
    draw_hint(hints, "Parts attach in the rig's rest pose; pose the armature "
                     "afterwards and they follow.")
    draw_hint(hints, "Texture or retopologize the body BEFORE Auto Rig.")
    if node.state == 'SUCCESS':
        layout.label(text=assemble_summary(node), icon='CHECKMARK')
    elif node.state == 'FAILED' and node.error:
        layout.label(text=node.error, icon='ERROR')

    actions = layout.column(align=True)
    run = actions.row()
    op = run.operator('mixie.moodboard_run_action_node', text="Assemble", icon='BONE_DATA')
    op.node_id = node.node_id
    if hasattr(run, 'mixar_style'):
        run.mixar_style(component='ACTION', variant='PRIMARY')
    reset = actions.row()
    op = reset.operator('mixie.moodboard_reset_node_params', text="Reset Settings")
    op.node_id = node.node_id
    if hasattr(reset, 'mixar_style'):
        reset.mixar_style(component='ACTION', variant='GHOST')
