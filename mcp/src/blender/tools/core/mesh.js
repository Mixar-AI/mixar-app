// Mesh tools — blender_mesh_create_primitive, blender_mesh_get_data, blender_mesh_set_data

import { sendToBlender } from "../../blender-bridge.js";

export const meshTools = [
  {
    name: "blender_mesh_create_primitive",
    description:
      "Create a mesh primitive object in the current Blender scene. " +
      "Supported types: CUBE, UV_SPHERE, ICO_SPHERE, CYLINDER, CONE, TORUS, PLANE, GRID, MONKEY. " +
      "Example call: { \"type\": \"CYLINDER\", \"name\": \"Pillar\", \"location\": [0, 0, 0], \"radius\": 0.5, \"depth\": 3.0, \"segments\": 32 }. " +
      "This tool does not support non-uniform scaling. For non-uniform scale, create the primitive first, then call blender_object_transform with the desired [x, y, z] scale. " +
      "Returns: { name, type, location, vertex_count, face_count }",
    inputSchema: {
      type: "object",
      properties: {
        type: {
          type: "string",
          enum: [
            "CUBE",
            "UV_SPHERE",
            "ICO_SPHERE",
            "CYLINDER",
            "CONE",
            "TORUS",
            "PLANE",
            "GRID",
            "MONKEY",
          ],
          description:
            "Type of primitive to create. Must be UPPERCASE and one of the enum values. " +
            "Example: \"CUBE\", \"UV_SPHERE\", \"CYLINDER\".",
        },
        name: {
          type: "string",
          description: "Optional name for the created object. Example: \"TableTop\".",
        },
        location: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "World-space position as a JSON array of exactly 3 numbers [x, y, z]. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. " +
            "Correct: [1.0, 0, 0.5] — Wrong: \"[1.0, 0, 0.5]\". Defaults to [0, 0, 0].",
        },
        size: {
          type: "number",
          description:
            "Overall size of the primitive (total extent, not radius). " +
            "For CUBE: size=2.0 creates a 2m cube (vertices at ±1.0m). " +
            "For PLANE: size=2.0 creates a 2m×2m plane. " +
            "Example: 2.0 (creates a 2m cube).",
        },
        radius: {
          type: "number",
          description:
            "Radius for sphere, cylinder, cone, and torus primitives. " +
            "Example: 0.5 (50cm radius).",
        },
        segments: {
          type: "integer",
          maximum: 1024,
          description:
            "Number of segments (UV_SPHERE longitude, CYLINDER/CONE sides, TORUS major). " +
            "Example: 32 (smooth circle) or 6 (hexagonal).",
        },
        rings: {
          type: "integer",
          maximum: 512,
          description:
            "Number of rings (UV_SPHERE latitude, TORUS minor segments). " +
            "Example: 16.",
        },
        vertices: {
          type: "integer",
          description:
            "Number of vertices (GRID x/y resolution; alias for segments on some types). " +
            "Example: 10.",
        },
        depth: {
          type: "number",
          description:
            "Height/depth for CYLINDER and CONE. " +
            "Example: 2.0 (2 meters tall).",
        },
        subdivisions: {
          type: "integer",
          maximum: 8,
          description:
            "Subdivision count for ICO_SPHERE. Higher = smoother. " +
            "Example: 2 (default), 4 (smooth).",
        },
      },
      required: ["type"],
    },
    handler: async (args) => {
      const result = await sendToBlender("mesh/create-primitive", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_mesh_get_data",
    description:
      "Get mesh data for a Blender mesh object: vertex, edge and face counts, " +
      "bounding box, UV layer names, vertex group names, and whether custom normals are present. " +
      "Returns: { name, vertex_count, edge_count, face_count, bounding_box, uv_layers, vertex_groups, has_custom_normals }",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Name of the mesh object to inspect. Example: \"Cube\".",
        },
      },
      required: ["name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("mesh/get-data", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_mesh_set_data",
    description:
      "Set mesh shading or smoothing properties on a Blender mesh object. " +
      "Example call: { \"name\": \"Sphere\", \"shade_smooth\": true, \"auto_smooth_angle\": 30 }. " +
      "Returns: { success, name, shade_smooth, auto_smooth_angle }",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Name of the mesh object to modify. Example: \"Sphere\".",
        },
        shade_smooth: {
          type: "boolean",
          description:
            "If true, apply smooth shading to all faces. If false, apply flat shading. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string. " +
            "Correct: true — Wrong: \"true\".",
        },
        auto_smooth_angle: {
          type: "number",
          description:
            "Auto smooth angle threshold in degrees (e.g. 30, 60, 180). " +
            "Only meaningful when shade_smooth is true. Example: 30.",
        },
      },
      required: ["name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("mesh/set-data", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
