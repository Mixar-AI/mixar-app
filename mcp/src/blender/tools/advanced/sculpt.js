// Advanced sculpt tools — sculpting mode, brushes, dyntopo, remesh, masks, face sets

import { sendToBlender } from "../../blender-bridge.js";

export const sculptTools = [
  {
    name: "blender_sculpt_enter",
    description:
      "Enter Sculpt Mode on the specified mesh object. " +
      "The object is selected, made active, and the mode is switched to SCULPT. " +
      "The object must be of type MESH. Returns the object name and active mode. " +
      "Example call: { \"object_name\": \"Landscape\" }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object to enter sculpt mode on.",
        },
      },
      required: ["object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("sculpt/enter", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_sculpt_exit",
    description:
      "Exit Sculpt Mode and return to Object Mode. " +
      "Call this after finishing sculpt operations. Returns the resulting mode.",
    inputSchema: {
      type: "object",
      properties: {},
      required: [],
    },
    handler: async (args) => {
      const result = await sendToBlender("sculpt/exit", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_sculpt_set_brush",
    description:
      "Set the active sculpt brush by type. " +
      "Supported brush types: DRAW, CLAY_STRIPS, GRAB, SNAKE_HOOK, SMOOTH, CREASE, INFLATE, " +
      "BLOB, FLATTEN, FILL, SCRAPE, PINCH, LAYER, NUDGE, ROTATE, THUMB, ELASTIC_DEFORM, " +
      "CLOTH_BRUSH, MASK, DRAW_FACE_SETS. " +
      "Must be in Sculpt Mode. Returns the active brush type.",
    inputSchema: {
      type: "object",
      properties: {
        brush_type: {
          type: "string",
          enum: [
            "DRAW",
            "CLAY_STRIPS",
            "GRAB",
            "SNAKE_HOOK",
            "SMOOTH",
            "CREASE",
            "INFLATE",
            "BLOB",
            "FLATTEN",
            "FILL",
            "SCRAPE",
            "PINCH",
            "LAYER",
            "NUDGE",
            "ROTATE",
            "THUMB",
            "ELASTIC_DEFORM",
            "CLOTH_BRUSH",
            "MASK",
            "DRAW_FACE_SETS",
          ],
          description: "The sculpt brush type to activate. Must be UPPERCASE.",
        },
      },
      required: ["brush_type"],
    },
    handler: async (args) => {
      const result = await sendToBlender("sculpt/set-brush", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_sculpt_configure_brush",
    description:
      "Configure properties of the currently active sculpt brush. " +
      "All parameters are optional — only the provided values are changed. " +
      "radius sets the brush size in pixels, strength sets the brush intensity (0–1), " +
      "auto_smooth sets the auto-smooth factor (0–1), " +
      "direction sets whether the brush adds or subtracts (ADD or SUBTRACT). " +
      "Must be in Sculpt Mode. Returns the resulting brush configuration.",
    inputSchema: {
      type: "object",
      properties: {
        radius: {
          type: "number",
          description: "Brush radius in pixels.",
        },
        strength: {
          type: "number",
          description: "Brush strength/intensity, in range 0.0 to 1.0.",
        },
        auto_smooth: {
          type: "number",
          description: "Auto smooth factor applied during the stroke, in range 0.0 to 1.0.",
        },
        direction: {
          type: "string",
          enum: ["ADD", "SUBTRACT"],
          description: "Brush direction. Must be UPPERCASE. ADD builds up geometry, SUBTRACT carves into it.",
        },
      },
      required: [],
    },
    handler: async (args) => {
      const result = await sendToBlender("sculpt/configure-brush", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_sculpt_stroke",
    description:
      "Execute a sculpt brush stroke through a sequence of 3D world-space points. " +
      "Each point is an [x, y, z] array in world coordinates. " +
      "An optional per-point pressure array controls brush intensity along the stroke. " +
      "Must be in Sculpt Mode with a 3D viewport available. " +
      "Returns the number of stroke points and the brush used.",
    inputSchema: {
      type: "object",
      properties: {
        points: {
          type: "array",
          items: {
            type: "array",
            items: { type: "number" },
            minItems: 3,
            maxItems: 3,
          },
          description:
            "List of [x, y, z] world-space positions for the stroke path. " +
            "IMPORTANT: Must be a JSON array of arrays, NOT a string. " +
            "Example: [[0, 0, 1], [0.5, 0, 1.2], [1, 0, 1]].",
        },
        pressure: {
          type: "array",
          items: { type: "number" },
          maxItems: 1000,
          description:
            "Optional list of pressure values (0.0–1.0) per stroke point. " +
            "If omitted, full pressure (1.0) is used for all points.",
        },
      },
      required: ["points"],
    },
    handler: async (args) => {
      const result = await sendToBlender("sculpt/stroke", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_sculpt_symmetry",
    description:
      "Configure sculpt symmetry mirroring on the active sculpt object. " +
      "Enable or disable X, Y, and Z axis mirroring independently. " +
      "use_symmetry is a master toggle; individual axis flags are applied on top. " +
      "Must be in Sculpt Mode. Returns the current symmetry state.",
    inputSchema: {
      type: "object",
      properties: {
        x: {
          type: "boolean",
          description:
            "Enable mirroring across the X axis. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string.",
        },
        y: {
          type: "boolean",
          description:
            "Enable mirroring across the Y axis. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string.",
        },
        z: {
          type: "boolean",
          description:
            "Enable mirroring across the Z axis. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string.",
        },
        use_symmetry: {
          type: "boolean",
          description:
            "Master toggle for symmetry. When false, all axis symmetry is disabled. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string.",
        },
      },
      required: [],
    },
    handler: async (args) => {
      const result = await sendToBlender("sculpt/symmetry", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_sculpt_dyntopo_enable",
    description:
      "Enable Dynamic Topology (Dyntopo) on the active sculpt object. " +
      "Dyntopo continuously subdivides or collapses edges during sculpting for adaptive detail. " +
      "Objects with shape keys are not supported and will return an error. " +
      "detail_size controls the target polygon size; detail_method controls how size is measured: " +
      "CONSTANT (world units), RELATIVE (relative to object size), or BRUSH (based on brush size). " +
      "Must be in Sculpt Mode. Returns enabled status, detail size, and method.",
    inputSchema: {
      type: "object",
      properties: {
        detail_size: {
          type: "number",
          description: "Target detail size for dynamic topology tessellation.",
        },
        detail_method: {
          type: "string",
          enum: ["CONSTANT", "RELATIVE", "BRUSH"],
          description: "Method used to compute the detail level. Must be UPPERCASE.",
        },
      },
      required: [],
    },
    handler: async (args) => {
      const result = await sendToBlender("sculpt/dyntopo-enable", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_sculpt_dyntopo_disable",
    description:
      "Disable Dynamic Topology (Dyntopo) on the active sculpt object. " +
      "This freezes the current mesh tessellation and stops adaptive subdivision. " +
      "Must be in Sculpt Mode with Dyntopo active. Returns disabled status.",
    inputSchema: {
      type: "object",
      properties: {},
      required: [],
    },
    handler: async (args) => {
      const result = await sendToBlender("sculpt/dyntopo-disable", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_sculpt_voxel_remesh",
    description:
      "Perform a voxel-based remesh on the specified mesh object. " +
      "This rebuilds the mesh topology at uniform density based on voxel_size — " +
      "smaller values produce higher resolution (more polygons). " +
      "The object must be in Object Mode before remeshing. " +
      "Returns the object name, voxel size used, and resulting vertex count.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object to remesh.",
        },
        voxel_size: {
          type: "number",
          description:
            "Voxel size for the remesh operation. Smaller values produce more polygons.",
        },
      },
      required: ["object_name", "voxel_size"],
    },
    handler: async (args) => {
      const result = await sendToBlender("sculpt/voxel-remesh", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_sculpt_mask_fill",
    description:
      "Perform a flood-fill operation on the sculpt mask. " +
      "FILL sets all vertices to fully masked (1.0). " +
      "CLEAR removes all masking (0.0). " +
      "INVERT flips the existing mask values. " +
      "SMOOTH applies a smoothing filter to the existing mask. " +
      "Must be in Sculpt Mode. Returns the action performed.",
    inputSchema: {
      type: "object",
      properties: {
        action: {
          type: "string",
          enum: ["FILL", "CLEAR", "INVERT", "SMOOTH"],
          description: "The mask flood-fill action to perform. Must be UPPERCASE.",
        },
      },
      required: ["action"],
    },
    handler: async (args) => {
      const result = await sendToBlender("sculpt/mask-fill", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_sculpt_face_sets_init",
    description:
      "Initialize face sets on the sculpt object based on a geometric feature. " +
      "NORMALS groups faces by similar normal direction. " +
      "UV_SEAMS creates sets bounded by UV seam edges. " +
      "SHARP_EDGES groups faces bounded by sharp (crease) edges. " +
      "MATERIALS groups faces by material slot assignment. " +
      "Must be in Sculpt Mode. Returns the initialization mode used.",
    inputSchema: {
      type: "object",
      properties: {
        mode: {
          type: "string",
          enum: ["NORMALS", "UV_SEAMS", "SHARP_EDGES", "MATERIALS"],
          description: "Feature to use when generating initial face set boundaries. Must be UPPERCASE.",
        },
      },
      required: ["mode"],
    },
    handler: async (args) => {
      const result = await sendToBlender("sculpt/face-sets-init", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_sculpt_multires_add",
    description:
      "Add a Multiresolution modifier to the specified mesh object and apply " +
      "one or more Catmull-Clark subdivision levels. " +
      "Multiresolution allows sculpting at different subdivision levels while " +
      "preserving low-resolution shape changes. " +
      "The object must be in Object Mode. " +
      "Returns the object name, modifier levels, and vertex count after subdivision.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object to add the Multiresolution modifier to.",
        },
        subdivisions: {
          type: "integer",
          maximum: 8,
          description:
            "Number of Catmull-Clark subdivision levels to add (default 1). " +
            "Higher values increase polygon count significantly.",
        },
      },
      required: ["object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("sculpt/multires-add", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_sculpt_multires_set_level",
    description:
      "Set the active sculpt level on an existing Multiresolution modifier. " +
      "This controls which subdivision level is used during sculpting. " +
      "The object must have a Multiresolution modifier already applied. " +
      "Returns the object name and the level that was set.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object with a Multiresolution modifier.",
        },
        level: {
          type: "integer",
          description: "The subdivision level to set as the active sculpt level.",
        },
      },
      required: ["object_name", "level"],
    },
    handler: async (args) => {
      const result = await sendToBlender("sculpt/multires-set-level", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_sculpt_remesh_quadriflow",
    description:
      "Perform QuadriFlow retopology on the specified mesh object to produce " +
      "an all-quad mesh with approximately the target face count. " +
      "This operation can be very slow on high-polygon meshes — plan accordingly. " +
      "The object must be in Object Mode. " +
      "Returns the object name, target face count, and actual face count after remeshing.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object to retopologize.",
        },
        target_faces: {
          type: "integer",
          description:
            "Target number of quad faces in the output mesh. " +
            "Actual count may differ slightly due to topology constraints.",
        },
      },
      required: ["object_name", "target_faces"],
    },
    handler: async (args) => {
      const result = await sendToBlender("sculpt/remesh-quadriflow", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_sculpt_detail_flood_fill",
    description:
      "Uniformize the mesh tessellation across the entire surface based on the " +
      "current Dyntopo detail size setting. " +
      "This re-tessellates all polygons to match the target detail level consistently. " +
      "Must be in Sculpt Mode with Dynamic Topology active. Returns success status.",
    inputSchema: {
      type: "object",
      properties: {},
      required: [],
    },
    handler: async (args) => {
      const result = await sendToBlender("sculpt/detail-flood-fill", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
