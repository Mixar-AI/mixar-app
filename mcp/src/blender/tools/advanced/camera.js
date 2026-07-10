// Advanced camera tools — create, configure, look-at, set-active, orbit, frame-object, render-settings

import { sendToBlender } from "../../blender-bridge.js";

export const cameraTools = [
  {
    name: "blender_camera_create",
    description:
      "Create a new camera object in the scene. " +
      "Accepts both 'camera_name' and 'name' parameters. " +
      "Example call: { \"camera_name\": \"MainCam\", \"location\": [7, -5, 3], \"rotation\": [1.1, 0, 0.8], \"focal_length\": 50 }. " +
      "Returns the new camera object name and its properties.",
    inputSchema: {
      type: "object",
      properties: {
        camera_name: {
          type: "string",
          description: "Name for the new camera object. Example: \"MainCam\".",
        },
        name: {
          type: "string",
          description:
            "Alias for camera_name (backward compatibility). Prefer camera_name for new calls.",
        },
        location: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "World-space position as a JSON array of 3 numbers [x, y, z]. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. " +
            "Example: [7.0, -5.0, 3.0]. Defaults to [0, 0, 0].",
        },
        rotation: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "Euler rotation in RADIANS as a JSON array of 3 numbers [x, y, z]. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. " +
            "Example: [1.1, 0, 0.8]. Defaults to [0, 0, 0].",
        },
        focal_length: {
          type: "number",
          description: "Focal length in millimetres. Example: 50. Defaults to 50.",
        },
      },
      required: [],
    },
    handler: async (args) => {
      const resolved = { ...args, camera_name: args.camera_name || args.name };
      if (!resolved.camera_name) {
        return JSON.stringify({ error: "Either 'camera_name' or 'name' is required." });
      }
      const result = await sendToBlender("camera/create", resolved);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_camera_configure",
    description:
      "Configure an existing camera's optical and depth-of-field properties. " +
      "Accepts both 'camera_name' and 'name' parameters. " +
      "Example call: { \"camera_name\": \"MainCam\", \"focal_length\": 85, \"dof\": { \"focus_distance\": 5.0, \"aperture_fstop\": 2.8 } }. " +
      "Returns the updated camera settings.",
    inputSchema: {
      type: "object",
      properties: {
        camera_name: {
          type: "string",
          description: "Name of the camera object to configure. Example: \"MainCam\".",
        },
        name: {
          type: "string",
          description:
            "Alias for camera_name (backward compatibility). Prefer camera_name for new calls.",
        },
        focal_length: {
          type: "number",
          description: "Focal length in millimetres. Example: 85.",
        },
        sensor_size: {
          type: "number",
          description: "Sensor width in millimetres. Example: 36.",
        },
        clip_start: {
          type: "number",
          description: "Near clipping distance. Example: 0.1.",
        },
        clip_end: {
          type: "number",
          description: "Far clipping distance. Example: 1000.",
        },
        dof: {
          type: "object",
          description:
            "Depth-of-field settings as a JSON object. " +
            "IMPORTANT: Must be a JSON object, NOT a string. " +
            "Example: { \"focus_distance\": 5.0, \"aperture_fstop\": 2.8 }.",
          properties: {
            focus_distance: {
              type: "number",
              description: "Distance to the focus plane in Blender units. Example: 5.0.",
            },
            aperture_fstop: {
              type: "number",
              description: "Aperture f-stop value (lower = shallower DOF). Example: 2.8.",
            },
          },
        },
      },
      required: [],
    },
    handler: async (args) => {
      const resolved = { ...args, camera_name: args.camera_name || args.name };
      if (!resolved.camera_name) {
        return JSON.stringify({ error: "Either 'camera_name' or 'name' is required." });
      }
      const result = await sendToBlender("camera/configure", resolved);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_camera_look_at",
    description:
      "Orient a camera so it points at a target. " +
      "Use target (string) for an object name, or target_point (array) for a coordinate. " +
      "Exactly one of target or target_point must be supplied. " +
      "Example with object: { \"camera_name\": \"MainCam\", \"target\": \"Cube\" }. " +
      "Example with point: { \"camera_name\": \"MainCam\", \"target_point\": [0, 0, 1] }.",
    inputSchema: {
      type: "object",
      properties: {
        camera_name: {
          type: "string",
          description: "Name of the camera object to reorient. Example: \"MainCam\".",
        },
        name: {
          type: "string",
          description:
            "Alias for camera_name (backward compatibility). Prefer camera_name for new calls.",
        },
        target: {
          type: "string",
          description:
            "Name of an existing scene object to look at (a string, NOT an array). " +
            "Mutually exclusive with target_point. Example: \"Cube\".",
        },
        target_point: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "Explicit world-space coordinate as a JSON array of 3 numbers [x, y, z]. " +
            "IMPORTANT: Must be a JSON array, NOT a string. " +
            "Mutually exclusive with target. Example: [0, 0, 1.0].",
        },
      },
      required: [],
    },
    handler: async (args) => {
      const resolved = { ...args, camera_name: args.camera_name || args.name };
      if (!resolved.camera_name) {
        return JSON.stringify({ error: "Either 'camera_name' or 'name' is required." });
      }
      const result = await sendToBlender("camera/look-at", resolved);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_camera_set_active",
    description:
      "Set a camera object as the active scene camera. Subsequent renders will use this camera. " +
      "The camera to make active. Accepts both 'camera_name' and 'name' parameters. " +
      "Example call: { \"camera_name\": \"MainCam\" }. " +
      "Returns the name of the newly active camera.",
    inputSchema: {
      type: "object",
      properties: {
        camera_name: {
          type: "string",
          description: "Name of the camera object to make active. Example: \"MainCam\".",
        },
        name: {
          type: "string",
          description:
            "Alias for camera_name (backward compatibility). Prefer camera_name for new calls.",
        },
      },
      required: [],
    },
    handler: async (args) => {
      const resolved = { ...args, camera_name: args.camera_name || args.name };
      if (!resolved.camera_name) {
        return JSON.stringify({ error: "Either 'camera_name' or 'name' is required." });
      }
      const result = await sendToBlender("camera/set-active", resolved);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_camera_orbit",
    description:
      "Set up an orbit animation where a camera circles a target object. " +
      "Creates an Empty, parents the camera to it, and keyframes a 360-degree Z rotation. " +
      "Example call: { \"target\": \"Cube\", \"radius\": 5, \"height\": 2, \"frames\": 120 }. " +
      "Returns the camera and empty object names along with keyframe info.",
    inputSchema: {
      type: "object",
      properties: {
        target: {
          type: "string",
          description: "Name of the scene object to orbit around. Example: \"Cube\".",
        },
        radius: {
          type: "number",
          description: "Orbit radius in Blender units. Example: 5. Defaults to 5.",
        },
        height: {
          type: "number",
          description: "Camera height relative to the target's origin. Example: 2. Defaults to 2.",
        },
        frames: {
          type: "integer",
          description: "Total number of frames for one full orbit. Example: 120. Defaults to 120.",
        },
      },
      required: ["target"],
    },
    handler: async (args) => {
      const result = await sendToBlender("camera/orbit", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_camera_frame_object",
    description:
      "Reposition the active camera so that the specified object fills the frame. " +
      "Example call: { \"object_name\": \"Table\", \"margin\": 1.3 }. " +
      "Returns camera position and rotation.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object to frame. Example: \"Table\".",
        },
        margin: {
          type: "number",
          description:
            "Padding factor (e.g. 1.2 = 20% extra space around object). Example: 1.3. Defaults to 1.2.",
        },
      },
      required: ["object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("camera/frame-object", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_camera_render_settings",
    description:
      "Configure global render output settings for the scene. " +
      "Example call: { \"resolution_x\": 1920, \"resolution_y\": 1080, \"format\": \"PNG\" }. " +
      "Returns the applied settings.",
    inputSchema: {
      type: "object",
      properties: {
        resolution_x: {
          type: "integer",
          maximum: 8192,
          description: "Render width in pixels. Example: 1920.",
        },
        resolution_y: {
          type: "integer",
          maximum: 8192,
          description: "Render height in pixels. Example: 1080.",
        },
        format: {
          type: "string",
          enum: ["PNG", "JPEG", "EXR"],
          description: "Output image file format. Must be UPPERCASE. Example: \"PNG\".",
        },
        filepath: {
          type: "string",
          description: "Output filepath for rendered images. Example: \"//render/frame_\".",
        },
      },
      required: [],
    },
    handler: async (args) => {
      const result = await sendToBlender("camera/render-settings", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
