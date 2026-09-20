# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What the canvas menus can offer, and how they offer it.

Split out of `moodboard_menus.py` when that file crossed the 500-line rule.
Both the right-click context menu and the output-plus continuation menu ask the
same questions — is this capability live on the moodboard surface, what mesh is
selected, where was the noodle dropped — so the answers live here rather than
being imported from one menu module into the other.
"""

from mixar.modules.moodboard.core import node_layout  # noqa: F401  (re-export)


def capability_available(capability: str) -> bool:
    """Whether this capability has an enabled model on the moodboard surface.

    The surface filter is not optional: services are tagged ``moodboard`` or
    ``paint``, and a paint-only service (``brush_gen`` under ``image_gen``)
    must never make a canvas action look available.
    """
    try:
        from mixar.bootstrap.generation_catalog_cache import get_models, get_services

        return any(
            get_models(service.get("key") or "")
            for service in get_services(capability, surface="moodboard")
        )
    except Exception:
        return False


MESH_CONTINUATIONS = (
    ('PBR_GEN', "PBR Generation", 'TEXTURE', "pbr_generation"),
    ('RETOPOLOGY', "Retopology", 'MOD_REMESH', "retopology"),
    ('MESH_SEGMENT', "Mesh Segmentation", 'MOD_EXPLODE', "mesh_segmentation"),
    ('AUTO_RIG', "Auto Rig", 'ARMATURE_DATA', "animate"),
)


def mesh_source_id(scene) -> str:
    """Node id of the active/selected node that currently holds a 3D mesh."""
    try:
        from mixar.modules.moodboard.core.node_graph import node_holds_mesh
    except Exception:
        return ""
    active = str(getattr(scene, "mixie_moodboard_active_node_id", "") or "")
    if active and node_holds_mesh(scene, active):
        return active
    for asset in getattr(scene, "mixie_moodboard_asset_nodes", ()):
        if asset.selected and node_holds_mesh(scene, asset.node_id):
            return asset.node_id
    for node in getattr(scene, "mixie_moodboard_action_nodes", ()):
        if node.selected and node_holds_mesh(scene, node.node_id):
            return node.node_id
    return ""


def connected_action(
    layout, action_type: str, text: str, icon: str, source="", drop=None,
    allow_empty=False,
):
    op = layout.operator(
        "mixie.moodboard_create_connected_action", text=text, icon=icon
    )
    op.action_type = action_type
    op.source_node_id = source
    if drop is not None:
        op.use_drop_position = True
        op.drop_x, op.drop_y = drop
    # Only the Shift+A Add menu sets this — a standalone node with no source.
    op.allow_empty = allow_empty
    return op


def link_drop_anchor(scene):
    """Canvas point a dragged noodle was released at, or None.

    Read-only: this runs from a menu draw, so it must never write scene data.
    The C++ graph modal sets the flag just before opening this menu and clears
    it at every other entry point, so a stale anchor cannot leak into a node
    created from the output handle or the right-click menu.
    """
    if not getattr(scene, "mixie_moodboard_link_drop_active", False):
        return None
    return (
        float(getattr(scene, "mixie_moodboard_link_drop_x", 0.0)),
        float(getattr(scene, "mixie_moodboard_link_drop_y", 0.0)),
    )
