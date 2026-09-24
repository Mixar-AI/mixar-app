# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Build the Character Sheet to 3D workflow: a framed graph of drafts.

Three reference cards (Body, Right-hand item, Left-hand item) read the sheet,
each feeds a Generate-to-3D card, the body's 3D card feeds Auto Rig (when the
catalog offers it), and everything meets in one Assemble card, with a how-to
note underneath. Nothing is submitted: every card is a DRAFT the user runs.

All or nothing. Any failure removes every card, link, note and frame the build
added and restores the selection, then surfaces as a ValueError the template
operator reports; the operator's UNDO flag makes a success one undo step.

Collection ``.add()`` reallocates the collection, which invalidates Python
references to its items, so cards are held by ``node_id`` and re-resolved.
The sheet itself can be a Generate Image card, so it is read into plain data
(ids, a name, rects) before the first card is added and never touched again.
The graph helpers are imported into this namespace so tests can replace them.
"""

from __future__ import annotations

import json

from ..constants import FRAME_SELECTION_PADDING, MOODBOARD_MULTI_IMAGE_GAP
from .assemble_constants import BODY_SOCKET, param_name, part_socket
from .asset_nodes import find_free_asset_position
from .character_sheet_catalog import IMAGE_SERVICE_KEY, preflight
from .character_sheet_workflow_spec import (
    ASSEMBLE_LABEL,
    DEFAULT_ROWS,
    FRAME_SHEET_NAME_BYTES,
    FRAME_STEM,
    FRAME_SUFFIX,
    LANES,
    NOTE_FONT,
    NOTE_WIDTH,
    NOTICE,
    RIG_LABEL,
    note_text,
)
from .frame_geometry import rects_overlap, unique_frame_name
from .frames import (
    board_items,
    create_frame,
    delete_frame,
    frame_rects,
    item_rect,
    select_frame,
)
from .graph_notice import post_graph_notice
from .media_utils import is_still_item
from .node_deletion import remove_action_node
from .node_graph import (
    action_node_by_id,
    connect_nodes,
    connect_to_next_input,
    create_connected_action,
    deselect_graph_nodes,
    ensure_media_node_ids,
    media_item_by_id,
    node_output_type,
)
from .node_schema import (
    refresh_node_parameter_visibility,
    set_node_selection,
    sync_node_schema,
)
from .node_templates import media_under_drop, template_available
from .workflow_layout import SHEET_GAP, note_height, plan_layout

# Every collection whose selection the build touches, restored on rollback.
_SELECTABLE = (
    "mixie_moodboard_images",
    "mixie_moodboard_textboxes",
    "mixie_moodboard_action_nodes",
    "mixie_moodboard_asset_nodes",
    "mixie_moodboard_frames",
)
# The image count parameter when the catalog does not name one; the image run
# path treats the same name as canonical.
_DEFAULT_COUNT_PARAM = "number_of_images"


def resolve_sheet_sources(scene, center, exact_position, source_node_id) -> list:
    """The sheet image(s) the reference cards read, in board order.

    An explicit source (a continuation from an image output) wins, then the
    still under an exact drop, then every selected standalone still. None is
    a valid answer: the note then asks the user to connect the sheet.
    """
    ensure_media_node_ids(scene)
    if source_node_id and node_output_type(scene, source_node_id) == 'IMAGE':
        source = media_item_by_id(scene, source_node_id) or action_node_by_id(
            scene, source_node_id
        )
        if source is not None:
            return [source]
    if exact_position:
        under = media_under_drop(scene, 'IMAGE_GEN', center)
        if under is not None:
            return [under]
    return [
        item for item in getattr(scene, "mixie_moodboard_images", ())
        if item.selected
        and getattr(item, "image", None) is not None
        and not getattr(item, "embedded_node_id", "")
        and is_still_item(item)
    ]


def _snapshot_selection(scene) -> dict:
    return {
        name: [bool(item.selected) for item in getattr(scene, name, ())]
        for name in _SELECTABLE
    }


def _restore_selection(scene, snapshot: dict, active_id: str) -> None:
    for name, states in snapshot.items():
        collection = getattr(scene, name, ())
        for item, selected in zip(collection, states):
            item.selected = selected
    scene.mixie_moodboard_active_node_id = active_id


def _sheet_name(source) -> str:
    image = getattr(source, "image", None) or getattr(source, "preview_image", None)
    name = str(getattr(image, "name", "") or "") if image is not None else ""
    return (name or str(getattr(source, "label", "") or "")).strip()


def _frame_name(scene, sheet: str) -> str:
    # The name's maxlen counts BYTES, so a multibyte sheet name is cut on a
    # byte budget; RNA would otherwise clip the suffix and repeat names.
    sheet = sheet.encode("utf-8")[:FRAME_SHEET_NAME_BYTES].decode("utf-8", "ignore").rstrip()
    base = sheet + FRAME_SUFFIX if sheet else FRAME_STEM
    existing = [frame.name for frame in getattr(scene, "mixie_moodboard_frames", ())]
    return base if base not in existing else unique_frame_name(existing, stem=base)


def _occupied(scene) -> list:
    """Rects of every board item (the sheet included) and every frame."""
    rects = [
        item_rect(item) for _name, item in board_items(scene)
        if not getattr(item, "embedded_node_id", "")
    ]
    rects.extend(rect for _frame_id, rect in frame_rects(scene))
    return [rect for rect in rects if rect is not None]


def _beside_sheet(scene, sheet_rects, bounds) -> tuple[float, float]:
    """Right of the whole sheet, top-aligned, slid right past anything in the way.

    The frame's padding sits between the gap and the first card, so the sheet
    stays outside the frame with a clear SHEET_GAP to its edge. Each step
    clears every blocker it met, so the slide ends within one step per item.
    """
    pad = FRAME_SELECTION_PADDING
    gap = MOODBOARD_MULTI_IMAGE_GAP
    left = max(rect[2] for rect in sheet_rects) + SHEET_GAP + pad
    top = max(rect[3] for rect in sheet_rects)
    occupied = _occupied(scene)
    for _step in range(len(occupied) + 1):
        frame = (left + bounds[0] - pad - gap, top + bounds[1] - pad - gap,
                 left + bounds[2] + pad + gap, top + bounds[3] + pad + gap)
        blockers = [rect for rect in occupied if rects_overlap(frame, rect)]
        if not blockers:
            break
        left = max(rect[2] for rect in blockers) + SHEET_GAP + pad
    return left, top


def _origin(scene, sheet_rects, center, bounds) -> tuple[float, float]:
    """Top-left corner of the workflow: beside the sheet, else in free space."""
    if sheet_rects:
        return _beside_sheet(scene, sheet_rects, bounds)
    # Sized as the FRAME (cards plus padding) so the padding stays clear too.
    pad = FRAME_SELECTION_PADDING
    width = bounds[2] - bounds[0] + 2.0 * pad
    height = bounds[3] - bounds[1] + 2.0 * pad
    left, bottom = find_free_asset_position(scene, float(center[0]), float(center[1]),
                                            width, height)
    return left + pad, bottom + height - pad


def _place(node, origin, offset) -> None:
    node.position_x = origin[0] + offset[0]
    node.position_y = origin[1] + offset[1]


def _parameter(node, name: str):
    return next((item for item in node.parameters if item.name == name), None)


def _choice_values(parameter) -> list[str]:
    try:
        choices = json.loads(parameter.choices_json or "[]")
    except (TypeError, ValueError):
        return []
    return [str(choice.get("value")) for choice in choices if isinstance(choice, dict)]


def _pin_single_image(node) -> None:
    """One image per reference card: the 3D card consumes exactly one."""
    try:
        from mixar.bootstrap.generation_catalog_cache import get_service

        service = get_service(IMAGE_SERVICE_KEY) or {}
    except Exception:
        service = {}
    name = (service.get("input_spec") or {}).get("cost_multiplier_param") or _DEFAULT_COUNT_PARAM
    parameter = _parameter(node, str(name))
    if parameter is not None:
        if parameter.parameter_type == 'INTEGER':
            parameter.value_integer = 1
        elif parameter.parameter_type == 'ENUM' and '1' in _choice_values(parameter):
            parameter.value_enum = '1'
    refresh_node_parameter_visibility(node)


def _free_socket(scene, node, kind: str) -> str:
    """The first unconnected input of *node* that accepts *kind*."""
    occupied = {
        link.to_socket for link in scene.mixie_moodboard_links
        if link.to_node_id == node.node_id
    }
    for socket in node.input_sockets:
        if socket.socket_id not in occupied and kind in socket.accepted_types.split(","):
            return socket.socket_id
    raise ValueError(f"This model has no free {kind.lower()} input")


def _new_card(scene, created: list, action_type: str, **kwargs):
    before = {node.node_id for node in scene.mixie_moodboard_action_nodes}
    try:
        node = create_connected_action(scene, action_type, **kwargs)
    except Exception:
        # The card is added before its catalog schema syncs, and only a failed
        # connect removes it again: record whatever the call left behind.
        created.extend(
            node.node_id for node in scene.mixie_moodboard_action_nodes
            if node.node_id and node.node_id not in before
        )
        raise
    created.append(node.node_id)
    return node


def _build_reference(scene, created, pf, label, prompt, source_ids, origin, offset) -> str:
    node = _new_card(scene, created, 'IMAGE_GEN', allow_empty=True)
    node_id = node.node_id
    set_node_selection(node, IMAGE_SERVICE_KEY, pf.image_slug)
    sync_node_schema(scene, node)
    _pin_single_image(node)
    node.label = label
    node.prompt = prompt
    node.requires_reference = True
    _place(node, origin, offset)
    for source_id in source_ids:
        target = action_node_by_id(scene, node_id)
        connect_nodes(scene, source_id, node_id, _free_socket(scene, target, 'IMAGE'))
    return node_id


def _build_rig(scene, created, body_3d_id, origin, offset) -> str:
    # Created unwired and connected by id: create_connected_action would hold
    # the body card's Python reference across its own ``.add()``.
    node = _new_card(scene, created, 'AUTO_RIG', allow_empty=True)
    node_id = node.node_id
    node.label = RIG_LABEL
    _place(node, origin, offset)
    connect_to_next_input(scene, body_3d_id, node_id)
    return node_id


def _build_model3d(scene, created, pf, ref_id, origin, offset) -> str:
    node = _new_card(scene, created, 'MODEL_3D', allow_empty=True)
    node_id = node.node_id
    set_node_selection(node, pf.model3d_service, pf.model3d_slug)
    sync_node_schema(scene, node)
    _place(node, origin, offset)
    target = action_node_by_id(scene, node_id)
    connect_nodes(scene, ref_id, node_id, _free_socket(scene, target, 'IMAGE'))
    return node_id


def _build_assemble(scene, created, body_id, part_ids, origin, offset) -> str:
    node = _new_card(scene, created, 'ASSEMBLE', allow_empty=True)
    node_id = node.node_id
    node.label = ASSEMBLE_LABEL
    _place(node, origin, offset)
    connect_nodes(scene, body_id, node_id, BODY_SOCKET)
    for index, part_id in enumerate(part_ids):
        connect_nodes(scene, part_id, node_id, part_socket(index))
    node = action_node_by_id(scene, node_id)
    for index, row in DEFAULT_ROWS.items():
        for kind, value in row.items():
            parameter = _parameter(node, param_name(kind, index))
            if parameter is None:
                raise ValueError("Assemble's settings are unavailable")
            parameter.value_enum = value
    return node_id


def _add_note(scene, notes: list, text, height, origin, offset) -> int:
    boxes = scene.mixie_moodboard_textboxes
    box = boxes.add()
    index = len(boxes) - 1
    # Recorded before any field write, so a failing write still rolls back.
    notes.append(index)
    box.text = text
    box.font_size = NOTE_FONT
    box.width = NOTE_WIDTH
    box.height = height
    _place(box, origin, offset)
    box.z_order = len(boxes) + len(scene.mixie_moodboard_images)
    return index


def _rollback(scene, created, notes, frame_id) -> None:
    if frame_id:
        delete_frame(scene, frame_id)
    boxes = getattr(scene, "mixie_moodboard_textboxes", None)
    for note_index in reversed(notes):
        if boxes is not None and 0 <= note_index < len(boxes):
            boxes.remove(note_index)
    for node_id in reversed(created):
        remove_action_node(scene, node_id)


def build_character_sheet_workflow(scene, *, sources: list, center):
    """Add the whole workflow as drafts and return its frame."""
    pf = preflight()
    if pf is None:
        raise ValueError(
            "This template needs an image model that accepts references and a 3D model "
            "that takes an image"
        )
    sources = list(sources or ())
    if len(sources) > pf.image_socket_count:
        raise ValueError(
            f"This image model takes at most {pf.image_socket_count} reference images; "
            "select fewer"
        )
    has_rig = template_available('AUTO_RIG')
    # Plain data only from here on: a card source goes stale at the first add.
    source_ids = [str(source.node_id) for source in sources]
    sheet = _sheet_name(sources[0]) if sources else ""
    sheet_rects = [rect for rect in map(item_rect, sources) if rect is not None]

    selection = _snapshot_selection(scene)
    active_id = str(getattr(scene, "mixie_moodboard_active_node_id", "") or "")
    # With nothing selected, create_connected_action cannot wire a card to the
    # selection behind the builder's back; the sheet is wired explicitly.
    for item in scene.mixie_moodboard_images:
        item.selected = False

    note = note_text(has_sheet=bool(source_ids), has_rig=has_rig)
    note_h = note_height(note, NOTE_FONT, NOTE_WIDTH)
    layout = plan_layout(len(LANES), has_rig, note_h, NOTE_WIDTH)
    origin = _origin(scene, sheet_rects, center, layout['bounds'])

    created: list[str] = []
    notes: list[int] = []
    frame_id = ""
    try:
        ref_ids = [
            _build_reference(scene, created, pf, label, prompt, source_ids, origin,
                             layout['ref'][row])
            for row, (_key, label, prompt) in enumerate(LANES)
        ]
        m3d_ids = [
            _build_model3d(scene, created, pf, ref_id, origin, layout['m3d'][row])
            for row, ref_id in enumerate(ref_ids)
        ]
        body_id = m3d_ids[0]
        if has_rig:
            body_id = _build_rig(scene, created, m3d_ids[0], origin, layout['rig'])
        _build_assemble(scene, created, body_id, m3d_ids[1:], origin, layout['assemble'])
        note_index = _add_note(scene, notes, note, note_h, origin, layout['note'])

        members = [action_node_by_id(scene, node_id) for node_id in created]
        members.append(scene.mixie_moodboard_textboxes[note_index])
        # Never the sheet: it stays where the user put it, outside the frame.
        frame = create_frame(scene, from_items=members, name=_frame_name(scene, sheet))
        if frame is None:
            raise ValueError("Frames are unavailable on this board")
        frame_id = frame.frame_id

        deselect_graph_nodes(scene)
        select_frame(scene, frame_id)
        post_graph_notice(scene, NOTICE, ref_ids[0])
        return frame
    except Exception as exc:
        _rollback(scene, created, notes, frame_id)
        _restore_selection(scene, selection, active_id)
        raise ValueError(str(exc)) from exc
