// Advanced animation extended tools — keyframes, actions, NLA, shape keys, drivers

import { sendToBlender } from "../../blender-bridge.js";

export const animationExtendedTools = [
  {
    name: "blender_anim_delete_keyframe",
    description:
      "Delete an existing keyframe on a specific data path of the named object at the given frame. " +
      "data_path is relative to the object (e.g. 'location', 'rotation_euler[1]'). " +
      "If no keyframe exists on that path at the specified frame, the operation is a no-op. " +
      "Returns the object name, data_path, and frame from which the keyframe was removed. " +
      "Example call: { \"object_name\": \"Cube\", \"data_path\": \"location\", \"frame\": 10 }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object from which to delete the keyframe.",
        },
        data_path: {
          type: "string",
          description:
            "RNA data path relative to the object, e.g. 'location', 'rotation_euler[1]'.",
        },
        frame: {
          type: "integer",
          description: "The frame number from which to delete the keyframe.",
        },
      },
      required: ["object_name", "data_path", "frame"],
    },
    handler: async (args) => {
      const result = await sendToBlender("anim/delete-keyframe", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_anim_set_frame_range",
    description:
      "Set the scene's animation frame range (start and end frames) and optionally the frame rate. " +
      "start and end define the playback/render range; fps sets the frames-per-second for the scene render. " +
      "Returns the resulting start frame, end frame, and fps values. " +
      "Example call: { \"start\": 1, \"end\": 250, \"fps\": 30 }.",
    inputSchema: {
      type: "object",
      properties: {
        start: {
          type: "integer",
          description: "The first frame of the scene animation range.",
        },
        end: {
          type: "integer",
          description: "The last frame of the scene animation range.",
        },
        fps: {
          type: "number",
          description: "Optional frames-per-second for the scene. Defaults to the current value if omitted.",
        },
      },
      required: ["start", "end"],
    },
    handler: async (args) => {
      const result = await sendToBlender("anim/set-frame-range", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_anim_set_current_frame",
    description:
      "DEPRECATED: Use the core tool blender_anim_set_frame instead. " +
      "blender_anim_set_frame is the primary, recommended tool for setting the current frame; " +
      "this tool is a legacy duplicate retained only for backwards compatibility. " +
      "Jump the scene's current frame to the specified frame number. " +
      "This updates the scene timeline, triggers frame-change callbacks, and evaluates all animated data " +
      "at the new frame. Returns the frame that was set.",
    inputSchema: {
      type: "object",
      properties: {
        frame: {
          type: "integer",
          description: "The frame number to set as the scene's current frame.",
        },
      },
      required: ["frame"],
    },
    handler: async (args) => {
      const result = await sendToBlender("anim/set-current-frame", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_anim_set_interpolation",
    description:
      "Set the keyframe interpolation mode for every keyframe point in every F-Curve of the object's " +
      "active action. " +
      "LINEAR produces straight transitions between values. " +
      "BEZIER uses smooth easing handles (the default in Blender). " +
      "CONSTANT holds the value until the next keyframe with no interpolation (stepped animation). " +
      "The object must have animation data and an assigned action. " +
      "Returns the object name, the interpolation mode applied, and the number of keyframe points modified. " +
      "Example call: { \"object_name\": \"Cube\", \"interpolation\": \"LINEAR\" }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object whose action keyframe interpolation will be changed.",
        },
        interpolation: {
          type: "string",
          enum: ["LINEAR", "BEZIER", "CONSTANT"],
          description: "Interpolation mode to apply to all keyframe points in the object's action. Must be UPPERCASE.",
        },
      },
      required: ["object_name", "interpolation"],
    },
    handler: async (args) => {
      const result = await sendToBlender("anim/set-interpolation", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_anim_create_action",
    description:
      "Create a new Action data-block with the given name and assign it to the specified object. " +
      "If the object does not yet have animation data, it is created automatically. " +
      "Any previously assigned action is replaced. " +
      "Returns the object name and the name of the newly created action. " +
      "Example call: { \"name\": \"WalkCycle\", \"object_name\": \"Armature\" }.",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Name for the new Action data-block.",
        },
        object_name: {
          type: "string",
          description: "Name of the object that will receive the new action.",
        },
      },
      required: ["name", "object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("anim/create-action", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_anim_assign_action",
    description:
      "Assign an existing Action data-block to the specified object. " +
      "The action must already exist in bpy.data.actions (e.g. created with blender_anim_create_action). " +
      "If the object does not yet have animation data, it is created automatically. " +
      "Returns the object name and the name of the action that was assigned. " +
      "Example call: { \"object_name\": \"Armature\", \"action_name\": \"WalkCycle\" }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object that will receive the action.",
        },
        action_name: {
          type: "string",
          description: "Name of the existing Action data-block to assign.",
        },
      },
      required: ["object_name", "action_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("anim/assign-action", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_anim_list_actions",
    description:
      "Return a list of all Action data-blocks currently present in the Blender file. " +
      "Each entry includes the action name, its frame range (first and last keyframe), " +
      "and the number of users (objects/data-blocks that reference it). " +
      "Useful for inspecting available animations before assigning or baking. " +
      "Example call: {}.",
    inputSchema: {
      type: "object",
      properties: {},
      required: [],
    },
    handler: async (args) => {
      const result = await sendToBlender("anim/list-actions", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_anim_bake",
    description:
      "Bake the animation of the specified object into individual keyframes over a frame range. " +
      "This evaluates the object's world-space transforms (or constraint results) frame by frame " +
      "and writes explicit keyframes, making the animation independent of constraints or drivers. " +
      "step controls how many frames to skip between baked keyframes (default 1 = every frame). " +
      "visual_keying is enabled, so constrained/parented transforms are baked as-seen in the viewport. " +
      "Returns the object name, baked frame range, and step used. " +
      "Example call: { \"object_name\": \"Cube\", \"start_frame\": 1, \"end_frame\": 100, \"step\": 2 }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object whose animation will be baked.",
        },
        start_frame: {
          type: "integer",
          description: "The first frame of the bake range.",
        },
        end_frame: {
          type: "integer",
          description: "The last frame of the bake range.",
        },
        step: {
          type: "integer",
          description: "Frame step between baked keyframes. Default is 1 (every frame).",
        },
      },
      required: ["object_name", "start_frame", "end_frame"],
    },
    handler: async (args) => {
      const result = await sendToBlender("anim/bake", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_anim_nla_push",
    description:
      "Push the object's active action down into the NLA (Non-Linear Animation) editor as a new NLA strip. " +
      "This converts the active action into a reusable NLA strip, freeing the action slot for a new action. " +
      "An optional strip_name renames the resulting NLA strip; if omitted the strip keeps its default name. " +
      "Returns the object name and the name of the NLA strip that was created. " +
      "Example call: { \"object_name\": \"Armature\", \"strip_name\": \"Idle\" }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object whose active action will be pushed to the NLA.",
        },
        strip_name: {
          type: "string",
          description: "Optional name to assign to the newly created NLA strip.",
        },
      },
      required: ["object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("anim/nla-push", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_anim_shape_key_add",
    description:
      "Add a new shape key to a mesh object. " +
      "The first shape key added to an object is always the Basis key (the reference shape); " +
      "subsequent keys define deformed versions of the mesh. " +
      "from_mix controls whether the new key is initialized from the current mix of all existing keys " +
      "(true) or from the Basis shape (false, the default). " +
      "The new key is renamed to the provided name. " +
      "Returns the object name and the name of the shape key that was created. " +
      "Example call: { \"object_name\": \"Face\", \"name\": \"Smile\", \"from_mix\": false }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object to add the shape key to.",
        },
        name: {
          type: "string",
          description: "Name for the new shape key.",
        },
        from_mix: {
          type: "boolean",
          description:
            "If true, initialize the new key from the current mix of existing shape keys. " +
            "If false (default), initialize from the Basis shape. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string.",
        },
      },
      required: ["object_name", "name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("anim/shape-key-add", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_anim_shape_key_set",
    description:
      "Set the influence value of a named shape key on a mesh object. " +
      "value must be between 0.0 (no influence, shape matches Basis) and 1.0 (full influence). " +
      "Values outside this range may be set but are non-standard. " +
      "This changes the current live value; use blender_anim_shape_key_keyframe to also insert a keyframe. " +
      "Returns the object name, key name, and the value that was set. " +
      "Example call: { \"object_name\": \"Face\", \"key_name\": \"Smile\", \"value\": 0.75 }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object that owns the shape key.",
        },
        key_name: {
          type: "string",
          description: "Name of the shape key whose value will be set.",
        },
        value: {
          type: "number",
          description: "Influence value to set, typically in range 0.0 to 1.0.",
        },
      },
      required: ["object_name", "key_name", "value"],
    },
    handler: async (args) => {
      const result = await sendToBlender("anim/shape-key-set", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_anim_shape_key_keyframe",
    description:
      "Set a shape key's influence value and insert a keyframe for it at the specified frame. " +
      "This is the combined equivalent of blender_anim_shape_key_set followed by a keyframe insert " +
      "on the shape key's 'value' property. " +
      "value must be in range 0.0 to 1.0. " +
      "Returns the object name, key name, value, and frame at which the keyframe was inserted. " +
      "Example call: { \"object_name\": \"Face\", \"key_name\": \"Smile\", \"frame\": 30, \"value\": 1.0 }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object that owns the shape key.",
        },
        key_name: {
          type: "string",
          description: "Name of the shape key to keyframe.",
        },
        frame: {
          type: "integer",
          description: "Frame number at which to insert the keyframe.",
        },
        value: {
          type: "number",
          description: "Influence value for the shape key at this frame, in range 0.0 to 1.0.",
        },
      },
      required: ["object_name", "key_name", "frame", "value"],
    },
    handler: async (args) => {
      const result = await sendToBlender("anim/shape-key-keyframe", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_anim_driver_add",
    description:
      "Add a driver to a specific data path on an object and set its Python expression. " +
      "A driver replaces keyframe animation with a Python expression that is evaluated every frame, " +
      "allowing properties to be controlled programmatically (e.g. driven by another property). " +
      "expression is a Python expression string such as 'sin(frame / 10)' or 'var * 2'. " +
      "Returns the object name, data_path, and the expression that was set. " +
      "Example call: { \"object_name\": \"Cube\", \"data_path\": \"location[0]\", \"expression\": \"sin(frame / 10)\" }.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object to add the driver to.",
        },
        data_path: {
          type: "string",
          description:
            "RNA data path relative to the object on which to add the driver, " +
            "e.g. 'location[0]', 'rotation_euler[2]', 'scale[1]'.",
        },
        expression: {
          type: "string",
          description:
            "Python expression for the driver, e.g. 'sin(frame / 10)' or 'var * 2.5'.",
        },
      },
      required: ["object_name", "data_path", "expression"],
    },
    handler: async (args) => {
      const result = await sendToBlender("anim/driver-add", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
