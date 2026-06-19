# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Assemble the layered scene graph dict from a registry + chosen relation layers."""

from scene_graph.registry import NodeRegistry, round_vec

SCHEMA = "mixar.scene_graph"
VERSION = 3

AXES_LEGEND = {
    "reference_frame": "world_axes",
    "x": "+X = right, -X = left",
    "y": "+Y = behind, -Y = in_front_of",
    "z": "+Z = above, -Z = below",
    "relation_format": "[subject_idx, object_idx, relation_type] => "
                       "nodes[subject] <relation_type> nodes[object] "
                       "(relation_type decoded against that layer's relation_types)",
}


def build_scene_graph(scene=None, layers=None, object_types=("MESH",)):
    """Build the v3 layered graph. `layers` defaults to [SpatialLayer()]."""
    if layers is None:
        from scene_graph.spatial_layer import SpatialLayer
        layers = [SpatialLayer()]

    reg = NodeRegistry.from_scene(scene, object_types=object_types)

    out_layers = {}
    for layer in layers:
        out_layers[layer.name] = {
            "relation_types": layer.legend(),
            "relations": layer.build(reg),
        }

    return {
        "schema": SCHEMA,
        "version": VERSION,
        "axes_legend": AXES_LEGEND,
        "scene_bounds": {
            "min": round_vec(reg.scene_min),
            "max": round_vec(reg.scene_max),
            "diagonal": round(reg.scene_diagonal, 4),
        },
        "node_count": len(reg.nodes),
        "nodes": [n.to_dict() for n in reg.nodes],
        "layers": out_layers,
    }
