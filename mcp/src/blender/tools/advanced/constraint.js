// Advanced constraint tools — object constraints management

import { sendToBlender } from "../../blender-bridge.js";

export const constraintTools = [
  {
    name: "blender_constraint_add",
    description:
      "Add a constraint to an object. " +
      "Supported types: COPY_LOCATION (copy another object's location), " +
      "COPY_ROTATION (copy another object's rotation), " +
      "COPY_SCALE (copy another object's scale), " +
      "TRACK_TO (make the object point toward a target), " +
      "DAMPED_TRACK (damped tracking toward a target axis), " +
      "LIMIT_LOCATION (restrict translation within min/max bounds), " +
      "LIMIT_ROTATION (restrict rotation within min/max bounds), " +
      "LIMIT_SCALE (restrict scale within min/max bounds), " +
      "FOLLOW_PATH (move the object along a curve path), " +
      "CLAMP_TO (clamp object position to a curve), " +
      "CHILD_OF (make the object behave as a child of a target without re-parenting), " +
      "FLOOR (prevent the object from passing through a target surface). " +
      "Returns the assigned constraint name (Blender may append a suffix for uniqueness). " +
      "Example call: { \"object_name\": \"Cube\", \"type\": \"COPY_LOCATION\" }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object to add the constraint to.",
        },
        type: {
          type: "string",
          enum: [
            "COPY_LOCATION",
            "COPY_ROTATION",
            "COPY_SCALE",
            "TRACK_TO",
            "DAMPED_TRACK",
            "LIMIT_LOCATION",
            "LIMIT_ROTATION",
            "LIMIT_SCALE",
            "FOLLOW_PATH",
            "CLAMP_TO",
            "CHILD_OF",
            "FLOOR",
          ],
          description: "The constraint type identifier. Must be UPPERCASE.",
        },
      },
      required: ["object_name", "type"],
    },
    handler: async (args) => {
      const result = await sendToBlender("constraint/add", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_constraint_remove",
    description:
      "Remove a named constraint from an object. " +
      "Use blender_constraint_list to retrieve the exact constraint name before calling this. " +
      "Returns the object name and the removed constraint name. " +
      "Example call: { \"object_name\": \"Cube\", \"constraint_name\": \"Copy Location\" }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object that owns the constraint.",
        },
        constraint_name: {
          type: "string",
          description:
            "Exact name of the constraint to remove (as returned by blender_constraint_list or blender_constraint_add).",
        },
      },
      required: ["object_name", "constraint_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("constraint/remove", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_constraint_configure",
    description:
      "Set one or more properties on an existing constraint via a params dictionary. " +
      "Only properties that exist on the constraint type are applied; unrecognised keys are skipped. " +
      "Common params by constraint type: " +
      "COPY_LOCATION/ROTATION/SCALE — use_x, use_y, use_z (bool), invert_x, invert_y, invert_z (bool), use_offset (bool); " +
      "TRACK_TO — track_axis ('TRACK_X','TRACK_Y','TRACK_Z','TRACK_NEGATIVE_X','TRACK_NEGATIVE_Y','TRACK_NEGATIVE_Z'), up_axis ('UP_X','UP_Y','UP_Z'); " +
      "LIMIT_LOCATION — use_min_x, min_x, use_max_x, max_x, use_min_y, min_y, use_max_y, max_y, use_min_z, min_z, use_max_z, max_z (floats/bools); " +
      "LIMIT_ROTATION — use_limit_x, min_x, max_x, use_limit_y, min_y, max_y, use_limit_z, min_z, max_z (degrees as floats); " +
      "FOLLOW_PATH — forward_axis ('FORWARD_X','FORWARD_Y','FORWARD_Z'), up_axis, use_fixed_location (bool), offset (float); " +
      "FLOOR — floor_location ('FLOOR_X','FLOOR_Y','FLOOR_Z','FLOOR_NEGATIVE_X','FLOOR_NEGATIVE_Y','FLOOR_NEGATIVE_Z'), offset (float), use_sticky (bool). " +
      "Returns a list of applied keys and any skipped keys. " +
      "Example call: { \"object_name\": \"Cube\", \"constraint_name\": \"Copy Location\", \"params\": { \"use_x\": true, \"use_y\": false, \"influence\": 0.5 } }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object that owns the constraint.",
        },
        constraint_name: {
          type: "string",
          description: "Name of the constraint to configure.",
        },
        params: {
          type: "object",
          description:
            "Key/value pairs to apply to the constraint. " +
            "IMPORTANT: Must be a JSON object, NOT a string. " +
            "Each key must match a valid Python attribute name on the constraint type. " +
            "Example: { \"use_x\": true, \"use_y\": false, \"influence\": 0.5 }.",
        },
      },
      required: ["object_name", "constraint_name", "params"],
    },
    handler: async (args) => {
      const result = await sendToBlender("constraint/configure", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_constraint_set_target",
    description:
      "Assign a target object (and optionally a target bone) to a constraint. " +
      "Applies to constraints that have a 'target' property such as COPY_LOCATION, COPY_ROTATION, " +
      "COPY_SCALE, TRACK_TO, DAMPED_TRACK, FOLLOW_PATH, CLAMP_TO, CHILD_OF, and FLOOR. " +
      "When targeting a specific bone on an armature, provide target_bone with the pose bone name. " +
      "Returns the object name, constraint name, resolved target object name, and target bone (if set). " +
      "Example call: { \"object_name\": \"Cube\", \"constraint_name\": \"Copy Location\", \"target_object\": \"Empty\" }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the constrained object.",
        },
        constraint_name: {
          type: "string",
          description: "Name of the constraint to update.",
        },
        target_object: {
          type: "string",
          description: "Name of the Blender object to use as the constraint target.",
        },
        target_bone: {
          type: "string",
          description:
            "Optional. Pose bone name when the target object is an armature and you want to track a specific bone.",
        },
      },
      required: ["object_name", "constraint_name", "target_object"],
    },
    handler: async (args) => {
      const result = await sendToBlender("constraint/set-target", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_constraint_set_influence",
    description:
      "Set the influence (blend weight) of a constraint, controlling how strongly it affects the object. " +
      "A value of 1.0 means full effect; 0.0 means no effect. " +
      "The value is automatically clamped to the [0.0, 1.0] range. " +
      "Returns the object name, constraint name, and the applied influence value. " +
      "Example call: { \"object_name\": \"Cube\", \"constraint_name\": \"Copy Location\", \"influence\": 0.5 }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the constrained object.",
        },
        constraint_name: {
          type: "string",
          description: "Name of the constraint to adjust.",
        },
        influence: {
          type: "number",
          minimum: 0,
          maximum: 1,
          description: "Influence value in the range 0.0 (no effect) to 1.0 (full effect).",
        },
      },
      required: ["object_name", "constraint_name", "influence"],
    },
    handler: async (args) => {
      const result = await sendToBlender("constraint/set-influence", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_constraint_list",
    description:
      "List all constraints on an object, returning their names, types, influence values, " +
      "mute state, and target object name (if any). " +
      "Use this to discover constraint names before calling configure, set-target, set-influence, or remove. " +
      "Example call: { \"object_name\": \"Cube\" }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object whose constraints to list.",
        },
      },
      required: ["object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("constraint/list", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
