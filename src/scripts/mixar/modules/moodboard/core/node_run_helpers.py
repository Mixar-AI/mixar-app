# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Small run-time rules every inference card obeys, whatever its action.

Split out of ``node_execution.py`` (500-line rule). bpy-free at import time;
the graph helpers are imported lazily, as ``node_execution`` imports them too.
"""

from __future__ import annotations

from .generation_names import sanitize_label
from .node_action_types import ACTION_TYPES

# The backend echoes the name into S3 keys and Blender datablock names, so a
# long card label is cut well inside both.
IMAGE_NAME_MAXLEN = 60

_ACTION_NAMES = {identifier: name for identifier, name, _description in ACTION_TYPES}


def producer_ready(scene, node_id: str) -> bool:
    """Whether the card at *node_id* has a result a downstream card can use.

    Media and asset cards ARE their content. An action card is ready once it
    succeeded, or while it still shows an earlier result (a re-run keeps the
    previous preview visible, and that preview is what feeds the graph).
    """
    from .node_graph import action_node_by_id

    node = action_node_by_id(scene, node_id)
    if node is None:
        return True
    return bool(
        node.state == 'SUCCESS'
        or getattr(node, "preview_image", None) is not None
        or getattr(node, "preview_object", None) is not None
        or str(getattr(node, "result_names", "") or "").strip()
    )


def _card_name(node) -> str:
    label = str(getattr(node, "label", "") or "").strip()
    return label or _ACTION_NAMES.get(node.action_type, "the connected card")


def require_upstream_results(scene, node) -> None:
    """Refuse to run a card whose connected producer has nothing to give yet.

    Without this, a card wired to an ungenerated card either submitted with
    the input silently missing or failed with a message about the wrong card.
    ASSEMBLE is exempt: it skips a part that is not generated yet and says so
    in its own report.
    """
    if node.action_type == 'ASSEMBLE':
        return
    from .node_graph import action_node_by_id

    for link in getattr(scene, "mixie_moodboard_links", ()):
        if link.to_node_id != node.node_id or producer_ready(scene, link.from_node_id):
            continue
        producer = action_node_by_id(scene, link.from_node_id)
        name = _card_name(producer)
        if producer.state in {'QUEUED', 'RUNNING'}:
            raise ValueError(f"Wait for '{name}' to finish — this card uses its result")
        raise ValueError(f"Generate '{name}' first — this card uses its result")


def label_image_name(node) -> str:
    """The generated image's name, taken from the card's label ("" = backend's)."""
    label = str(getattr(node, "label", "") or "")
    return sanitize_label(label)[:IMAGE_NAME_MAXLEN] if label.strip() else ""


def grow_owner_frame(scene, node) -> None:
    """Stretch the card's frame around it after a result resized the card.

    Grow-only and idempotent. Called from the result import timer, never from
    a draw callback.
    """
    frame_id = str(getattr(node, "frame_id", "") or "")
    if not frame_id:
        return
    from .frames import grow_frames_to_fit_members

    grow_frames_to_fit_members(scene, [frame_id])
