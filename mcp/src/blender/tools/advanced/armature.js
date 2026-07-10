// Advanced armature tools — skeleton creation, bones, rigging, weight painting, posing

import { sendToBlender } from "../../blender-bridge.js";

export const armatureTools = [
  {
    name: "blender_armature_create",
    description:
      "Create a new armature object in the scene. " +
      "An empty armature data block is created and linked to the collection at the given location. " +
      "Example call: { \"name\": \"Skeleton\", \"location\": [0, 0, 0] }. " +
      "Returns the armature object name and its world location.",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Name for the new armature object.",
        },
        location: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "World-space location as a JSON array of 3 numbers [x, y, z]. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. " +
            "Example: [0, 0, 0]. Defaults to [0, 0, 0].",
        },
      },
      required: ["name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("armature/create", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_armature_add_bone",
    description:
      "Add a new bone to an existing armature. " +
      "The armature is temporarily set to Edit Mode, the bone created with the given head/tail " +
      "positions, optionally parented to an existing bone, then returned to Object Mode. " +
      "Example call: { \"armature_name\": \"Skeleton\", \"bone_name\": \"spine\", \"head\": [0, 0, 0], \"tail\": [0, 0, 0.5] }. " +
      "Returns the armature name, new bone name, head, and tail positions.",
    inputSchema: {
      type: "object",
      properties: {
        armature_name: {
          type: "string",
          description: "Name of the armature object.",
        },
        bone_name: {
          type: "string",
          description: "Name for the new bone.",
        },
        head: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "Head (root) position of the bone as a JSON array [x, y, z] in armature local space. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. Example: [0, 0, 0].",
        },
        tail: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "Tail (tip) position of the bone as a JSON array [x, y, z] in armature local space. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. Example: [0, 0, 0.5].",
        },
        parent_bone: {
          type: "string",
          description: "Optional name of an existing bone to parent the new bone to.",
        },
      },
      required: ["armature_name", "bone_name", "head", "tail"],
    },
    handler: async (args) => {
      const result = await sendToBlender("armature/add-bone", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_armature_edit_bone",
    description:
      "Modify properties of an existing bone in an armature. " +
      "Supports changing head/tail positions, roll angle (in degrees), and the connected flag. " +
      "Only the provided properties are updated; omitted ones remain unchanged. " +
      "Returns the armature name, bone name, and all updated properties.",
    inputSchema: {
      type: "object",
      properties: {
        armature_name: {
          type: "string",
          description: "Name of the armature object.",
        },
        bone_name: {
          type: "string",
          description: "Name of the bone to modify.",
        },
        head: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "New head (root) position as a JSON array [x, y, z] in armature local space. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. Example: [0, 0, 0].",
        },
        tail: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "New tail (tip) position as a JSON array [x, y, z] in armature local space. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. Example: [0, 0, 0.5].",
        },
        roll: {
          type: "number",
          description: "Roll angle of the bone in degrees.",
        },
        connected: {
          type: "boolean",
          description:
            "Whether the bone head is connected to its parent's tail. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string. " +
            "Only meaningful if the bone has a parent.",
        },
      },
      required: ["armature_name", "bone_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("armature/edit-bone", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_armature_delete_bone",
    description:
      "Delete a bone from an armature. " +
      "Enters Edit Mode, removes the named bone, then returns to Object Mode. " +
      "Returns the armature name and the deleted bone name.",
    inputSchema: {
      type: "object",
      properties: {
        armature_name: {
          type: "string",
          description: "Name of the armature object.",
        },
        bone_name: {
          type: "string",
          description: "Name of the bone to delete.",
        },
      },
      required: ["armature_name", "bone_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("armature/delete-bone", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_armature_parent_to_mesh",
    description:
      "Parent a mesh to an armature using the specified weighting method. " +
      "AUTO generates automatic weights from bone envelopes and proximity. " +
      "EMPTY creates vertex groups without weights (manual painting required). " +
      "ENVELOPE uses bone envelope volumes for automatic weighting. " +
      "Returns the armature name, mesh name, and method used.",
    inputSchema: {
      type: "object",
      properties: {
        armature_name: {
          type: "string",
          description: "Name of the armature object.",
        },
        mesh_name: {
          type: "string",
          description: "Name of the mesh object to parent.",
        },
        method: {
          type: "string",
          enum: ["AUTO", "EMPTY", "ENVELOPE"],
          description:
            "Parenting method. Must be UPPERCASE. AUTO = automatic weights, EMPTY = no weights, ENVELOPE = envelope weights.",
        },
      },
      required: ["armature_name", "mesh_name", "method"],
    },
    handler: async (args) => {
      const result = await sendToBlender("armature/parent-to-mesh", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_armature_list_bones",
    description:
      "List all bones in an armature with their properties. " +
      "Returns bone name, head position, tail position, parent name, bone length, " +
      "and whether the bone is connected to its parent.",
    inputSchema: {
      type: "object",
      properties: {
        armature_name: {
          type: "string",
          description: "Name of the armature object.",
        },
      },
      required: ["armature_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("armature/list-bones", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_armature_set_bone_constraint",
    description:
      "Add or replace a constraint on a pose bone. " +
      "Enters Pose Mode, creates the named constraint type on the specified bone, " +
      "then applies all key/value pairs from the params object as constraint attributes. " +
      "Common constraint types: COPY_ROTATION, COPY_LOCATION, COPY_TRANSFORMS, " +
      "LIMIT_ROTATION, LIMIT_LOCATION, TRACK_TO, LOCKED_TRACK, DAMPED_TRACK, " +
      "STRETCH_TO, INVERSE_KINEMATICS, CHILD_OF, FLOOR, FOLLOW_PATH. " +
      "Returns armature name, bone name, constraint type, and auto-assigned constraint name.",
    inputSchema: {
      type: "object",
      properties: {
        armature_name: {
          type: "string",
          description: "Name of the armature object.",
        },
        bone_name: {
          type: "string",
          description: "Name of the pose bone.",
        },
        constraint_type: {
          type: "string",
          description:
            "Blender constraint type identifier (e.g., 'COPY_ROTATION', 'LIMIT_LOCATION').",
        },
        params: {
          type: "object",
          description:
            "Constraint-specific parameters as key/value pairs applied directly to the constraint. " +
            "IMPORTANT: Must be a JSON object, NOT a string. " +
            "Examples: { \"target\": \"ObjectName\" }, { \"influence\": 0.5 }, { \"use_x\": true, \"use_y\": false }.",
        },
      },
      required: ["armature_name", "bone_name", "constraint_type", "params"],
    },
    handler: async (args) => {
      const result = await sendToBlender("armature/set-bone-constraint", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_armature_remove_constraint",
    description:
      "Remove a named constraint from a pose bone. " +
      "Enters Pose Mode, finds the constraint by name, and removes it. " +
      "Returns the armature name, bone name, and the removed constraint name.",
    inputSchema: {
      type: "object",
      properties: {
        armature_name: {
          type: "string",
          description: "Name of the armature object.",
        },
        bone_name: {
          type: "string",
          description: "Name of the pose bone.",
        },
        constraint_name: {
          type: "string",
          description: "Name of the constraint to remove.",
        },
      },
      required: ["armature_name", "bone_name", "constraint_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("armature/remove-constraint", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_armature_set_ik",
    description:
      "Set up an Inverse Kinematics (IK) constraint on a pose bone. " +
      "Adds an INVERSE_KINEMATICS constraint with the specified chain length. " +
      "Optionally assigns a target object (end effector) and a pole target (to control elbow/knee direction). " +
      "Returns armature name, bone name, chain length, target, and pole_target.",
    inputSchema: {
      type: "object",
      properties: {
        armature_name: {
          type: "string",
          description: "Name of the armature object.",
        },
        bone_name: {
          type: "string",
          description: "Name of the pose bone to add IK to.",
        },
        chain_length: {
          type: "integer",
          description:
            "Number of bones in the IK chain. 0 means unlimited (reaches the root).",
        },
        target: {
          type: "string",
          description: "Optional name of the target object the IK chain tracks.",
        },
        pole_target: {
          type: "string",
          description:
            "Optional name of the pole target object that controls the chain's bend direction.",
        },
      },
      required: ["armature_name", "bone_name", "chain_length"],
    },
    handler: async (args) => {
      const result = await sendToBlender("armature/set-ik", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_armature_auto_rig",
    description:
      "Auto-rig a mesh using the Rigify addon. " +
      "Enables the rigify addon, generates an appropriate human or animal metarig, " +
      "positions it at the mesh origin, and parents it to the mesh with automatic weights. " +
      "Returns the mesh name, rig type, and the generated armature name.",
    inputSchema: {
      type: "object",
      properties: {
        mesh_name: {
          type: "string",
          description: "Name of the mesh object to rig.",
        },
        type: {
          type: "string",
          enum: ["HUMAN", "ANIMAL"],
          description: "Metarig type to generate. Must be UPPERCASE. Defaults to HUMAN.",
        },
      },
      required: ["mesh_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("armature/auto-rig", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_armature_weight_paint_auto",
    description:
      "Apply automatic vertex weights from an armature to a mesh. " +
      "Selects the mesh then the armature, sets armature as active, and calls parent_set " +
      "with ARMATURE_AUTO to generate per-bone vertex groups with heat-diffuse weights. " +
      "Returns the armature name and mesh name.",
    inputSchema: {
      type: "object",
      properties: {
        armature_name: {
          type: "string",
          description: "Name of the armature object.",
        },
        mesh_name: {
          type: "string",
          description: "Name of the mesh object to receive the weights.",
        },
      },
      required: ["armature_name", "mesh_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("armature/weight-paint-auto", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_armature_weight_paint_normalize",
    description:
      "Normalize all vertex group weights on a mesh so they sum to 1.0 per vertex. " +
      "Enters Weight Paint mode on the mesh and calls vertex_group_normalize_all. " +
      "Returns the mesh name.",
    inputSchema: {
      type: "object",
      properties: {
        mesh_name: {
          type: "string",
          description: "Name of the mesh object whose weights to normalize.",
        },
      },
      required: ["mesh_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("armature/weight-paint-normalize", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_armature_weight_assign",
    description:
      "Manually assign vertex weights to a named vertex group on a mesh. " +
      "Creates the vertex group if it does not exist. " +
      "All specified vertex indices receive the given weight value (0.0–1.0). " +
      "Returns the mesh name, group name, number of vertices assigned, and the weight value.",
    inputSchema: {
      type: "object",
      properties: {
        mesh_name: {
          type: "string",
          description: "Name of the mesh object.",
        },
        group_name: {
          type: "string",
          description: "Name of the vertex group (typically matches a bone name).",
        },
        vertex_indices: {
          type: "array",
          items: { type: "integer" },
          description:
            "Array of vertex indices to assign. " +
            "IMPORTANT: Must be a JSON array of integers, NOT a string. " +
            "Example: [0, 1, 2, 10, 11].",
        },
        weight: {
          type: "number",
          description: "Weight value to assign, in the range 0.0 (no influence) to 1.0 (full influence).",
        },
      },
      required: ["mesh_name", "group_name", "vertex_indices", "weight"],
    },
    handler: async (args) => {
      const result = await sendToBlender("armature/weight-assign", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_armature_pose_bone",
    description:
      "Set the pose transform of a bone in an armature. " +
      "Rotation is specified in Euler degrees [x, y, z] and applied as XYZ rotation order. " +
      "Location offsets the bone from its rest position in pose space. " +
      "Returns the armature name, bone name, and the applied rotation/location values.",
    inputSchema: {
      type: "object",
      properties: {
        armature_name: {
          type: "string",
          description: "Name of the armature object.",
        },
        bone_name: {
          type: "string",
          description: "Name of the pose bone to transform.",
        },
        rotation: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "Euler rotation in degrees as a JSON array [x, y, z]. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. " +
            "Example: [45, 0, 0].",
        },
        location: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "Location offset in pose space as a JSON array [x, y, z]. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. " +
            "Example: [0, 0, 0.1].",
        },
      },
      required: ["armature_name", "bone_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("armature/pose-bone", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_armature_pose_reset",
    description:
      "Reset pose bones to their rest position by clearing rotation, location, and scale. " +
      "If a bones array is provided, only those bones are reset; otherwise all bones are reset. " +
      "Returns the armature name and the list of bone names that were reset.",
    inputSchema: {
      type: "object",
      properties: {
        armature_name: {
          type: "string",
          description: "Name of the armature object.",
        },
        bones: {
          type: "array",
          items: { type: "string" },
          description:
            "Optional list of bone names to reset as a JSON array of strings. " +
            "IMPORTANT: Must be a JSON array, NOT a string. " +
            "Example: [\"spine\", \"arm.L\"]. If omitted or empty, all bones are reset.",
        },
      },
      required: ["armature_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("armature/pose-reset", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_armature_symmetrize",
    description:
      "Symmetrize bones across the armature's local X axis. " +
      "LEFT_TO_RIGHT copies bones on the -X (left) side to the +X (right) side. " +
      "RIGHT_TO_LEFT copies bones on the +X (right) side to the -X (left) side. " +
      "Bone names must follow Blender's naming convention (e.g., arm.L / arm.R) " +
      "for the symmetrize operator to correctly rename mirrored bones. " +
      "Returns the armature name and the direction used.",
    inputSchema: {
      type: "object",
      properties: {
        armature_name: {
          type: "string",
          description: "Name of the armature object.",
        },
        direction: {
          type: "string",
          enum: ["LEFT_TO_RIGHT", "RIGHT_TO_LEFT"],
          description:
            "Must be UPPERCASE. LEFT_TO_RIGHT: -X side overwrites +X side. RIGHT_TO_LEFT: +X side overwrites -X side.",
        },
      },
      required: ["armature_name", "direction"],
    },
    handler: async (args) => {
      const result = await sendToBlender("armature/symmetrize", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_armature_bone_layers",
    description:
      "Assign a bone to layers or bone collections. " +
      "In Blender 3.x, layers is an array of integer layer indices (0–31) to activate for the bone. " +
      "In Blender 4.x, layers is an array of collection name strings; collections are created if absent. " +
      "Returns the armature name, bone name, and assigned layers/collections.",
    inputSchema: {
      type: "object",
      properties: {
        armature_name: {
          type: "string",
          description: "Name of the armature object.",
        },
        bone_name: {
          type: "string",
          description: "Name of the bone.",
        },
        layers: {
          type: "array",
          description:
            "IMPORTANT: Must be a JSON array, NOT a string. " +
            "Blender 3.x: array of integer layer indices (0-31). Example: [0, 1, 16]. " +
            "Blender 4.x: array of bone collection name strings. Example: [\"IK\", \"FK\"].",
          items: {
            oneOf: [
              { type: "integer", minimum: 0, maximum: 31 },
              { type: "string" },
            ],
          },
        },
      },
      required: ["armature_name", "bone_name", "layers"],
    },
    handler: async (args) => {
      const result = await sendToBlender("armature/bone-layers", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_armature_rename_bones",
    description:
      "Batch rename bones in an armature using an old-name to new-name mapping. " +
      "Enters Edit Mode and renames each bone found in the mapping. " +
      "Bones not present in the armature are skipped and reported. " +
      "Returns the armature name, count of successfully renamed bones, " +
      "and a result map of old_name → new_name or error string.",
    inputSchema: {
      type: "object",
      properties: {
        armature_name: {
          type: "string",
          description: "Name of the armature object.",
        },
        mapping: {
          type: "object",
          description:
            "Dictionary of old bone names to new bone names. " +
            "IMPORTANT: Must be a JSON object, NOT a string. " +
            "Example: { \"Bone\": \"spine\", \"Bone.001\": \"hip\" }.",
          additionalProperties: { type: "string" },
        },
      },
      required: ["armature_name", "mapping"],
    },
    handler: async (args) => {
      const result = await sendToBlender("armature/rename-bones", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
