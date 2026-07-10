// SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
// SPDX-License-Identifier: GPL-3.0-or-later

// Scene introspection: the client-side scene-graph tool registry the hosted
// agent already consumes, plus convenience script templates for common reads.

import { callBridgeChecked, asText } from "../bridge.js";

const SCENE_INFO_SCRIPT = `
scene = bpy.context.scene
objects = []
for obj in list(scene.objects)[:__PARAMS__.get("limit", 200)]:
    objects.append({
        "name": obj.name,
        "type": obj.type,
        "location": [round(v, 4) for v in obj.location],
        "visible": obj.visible_get(),
        "parent": obj.parent.name if obj.parent else None,
    })
__RESULT__ = {
    "scene": scene.name,
    "object_count": len(scene.objects),
    "frame_current": scene.frame_current,
    "objects": objects,
}
`;

const OBJECT_INFO_SCRIPT = `
name = __PARAMS__["object_name"]
obj = bpy.data.objects.get(name)
if obj is None:
    __RESULT__ = {"found": False, "error": "object '%s' not found" % name}
else:
    info = {
        "found": True,
        "name": obj.name,
        "type": obj.type,
        "location": [round(v, 4) for v in obj.location],
        "rotation_euler": [round(v, 4) for v in obj.rotation_euler],
        "scale": [round(v, 4) for v in obj.scale],
        "dimensions": [round(v, 4) for v in obj.dimensions],
        "parent": obj.parent.name if obj.parent else None,
        "children": [c.name for c in obj.children],
        "collections": [c.name for c in obj.users_collection],
        "modifiers": [m.name for m in getattr(obj, "modifiers", [])],
        "materials": [s.material.name for s in getattr(obj, "material_slots", []) if s.material],
    }
    if obj.type == "MESH":
        info["mesh"] = {
            "vertices": len(obj.data.vertices),
            "polygons": len(obj.data.polygons),
            "uv_layers": [uv.name for uv in obj.data.uv_layers],
        }
    __RESULT__ = info
`;

export const sceneTools = [
  {
    name: "mixar_scene_graph",
    description:
      "Query Mixar's live scene graph (the hierarchy index the hosted agent uses). " +
      "Tools: scene_graph_summary (overview), roots, children, descendants, ancestors, " +
      "describe_object (all take object_name except summary/roots), get_graph (full graph — large scenes: prefer traversal tools).",
    inputSchema: {
      type: "object",
      properties: {
        tool: {
          type: "string",
          enum: [
            "scene_graph_summary",
            "roots",
            "children",
            "descendants",
            "ancestors",
            "describe_object",
            "get_graph",
          ],
          description: "Scene-graph query to run",
        },
        object_name: {
          type: "string",
          description: "Target object (required for children/descendants/ancestors/describe_object)",
        },
      },
      required: ["tool"],
    },
    handler: async (args) => {
      const params = args.object_name ? { object_name: args.object_name } : {};
      return asText(
        await callBridgeChecked("/tool", { domain: "scene_graph", name: args.tool, params })
      );
    },
  },
  {
    name: "mixar_scene_info",
    description:
      "Snapshot of the active Mixar scene: name, frame, and the object list " +
      "(name/type/location/visibility/parent).",
    inputSchema: {
      type: "object",
      properties: {
        limit: {
          type: "number",
          description: "Max objects to list (default 200)",
        },
      },
    },
    handler: async (args) =>
      asText(
        await callBridgeChecked("/execute", {
          script: SCENE_INFO_SCRIPT,
          params: { limit: args.limit || 200 },
          push_undo: false,
        })
      ),
  },
  {
    name: "mixar_object_info",
    description:
      "Detailed info for one object: transform, dimensions, hierarchy, collections, " +
      "modifiers, materials, and mesh stats for meshes.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: { type: "string", description: "Name of the object" },
      },
      required: ["object_name"],
    },
    handler: async (args) =>
      asText(
        await callBridgeChecked("/execute", {
          script: OBJECT_INFO_SCRIPT,
          params: { object_name: args.object_name },
          push_undo: false,
        })
      ),
  },
];
