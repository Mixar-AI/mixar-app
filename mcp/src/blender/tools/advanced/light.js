// Advanced light tools — create, configure, sun setup, three-point, HDRI, world color, list, shadow

import { sendToBlender } from "../../blender-bridge.js";

export const lightTools = [
  {
    name: "blender_light_create",
    description:
      "Create a new light object in the scene. " +
      "Supported types: POINT (omnidirectional), SUN (directional infinite), " +
      "SPOT (cone spotlight), AREA (rectangular/disk area light). " +
      "Example call: { \"type\": \"POINT\", \"name\": \"MyLight\", \"location\": [2, -3, 4], \"energy\": 1000, \"color\": [1, 0.9, 0.8] }. " +
      "Returns the new light object name and its data properties.",
    inputSchema: {
      type: "object",
      properties: {
        type: {
          type: "string",
          enum: ["POINT", "SUN", "SPOT", "AREA"],
          description:
            "Light type to create. Must be UPPERCASE. Example: \"POINT\".",
        },
        name: {
          type: "string",
          description: "Name for the new light object. Example: \"KeyLight\".",
        },
        location: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "Initial world-space position as a JSON array of 3 numbers [x, y, z]. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. " +
            "Example: [2.0, -3.0, 4.0]. Defaults to [0, 0, 0].",
        },
        energy: {
          type: "number",
          description: "Light power in watts. Example: 1000. Defaults vary by type.",
        },
        color: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "RGB color as a JSON array of 3 numbers [r, g, b], each 0.0 to 1.0. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. " +
            "Example: [1.0, 0.9, 0.8] (warm white). Defaults to [1, 1, 1].",
        },
      },
      required: ["type", "name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("light/create", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_light_configure",
    description:
      "Configure properties of an existing light object. " +
      "Can set energy, color, radius (shadow soft size), spot cone angle, and shadow on/off. " +
      "Example call: { \"name\": \"KeyLight\", \"energy\": 1500, \"color\": [1, 1, 1], \"shadow\": true }. " +
      "Returns the updated light properties.",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Name of the light object to configure. Example: \"KeyLight\".",
        },
        energy: {
          type: "number",
          description: "Light power in watts. Example: 1500.",
        },
        color: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "RGB color as a JSON array of 3 numbers [r, g, b], each 0.0 to 1.0. " +
            "IMPORTANT: Must be a JSON array, NOT a string. " +
            "Example: [1.0, 0.95, 0.9].",
        },
        radius: {
          type: "number",
          description: "Shadow soft size (light source radius in meters). Example: 0.25.",
        },
        angle: {
          type: "number",
          description: "Spot cone half-angle in degrees. Only applies to SPOT lights. Example: 45.",
        },
        shadow: {
          type: "boolean",
          description:
            "Enable (true) or disable (false) shadow casting for this light. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string. " +
            "Correct: true — Wrong: \"true\".",
        },
      },
      required: ["name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("light/configure", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_light_sun_setup",
    description:
      "Create or reconfigure a SUN light for scene-wide directional lighting. " +
      "If a SUN light already exists it will be updated; otherwise a new one is created. " +
      "Example call: { \"rotation\": [45, 0, 30], \"energy\": 5.0, \"color\": [1, 0.98, 0.95] }. " +
      "Returns the sun light object name and final properties.",
    inputSchema: {
      type: "object",
      properties: {
        rotation: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "Euler XYZ rotation in DEGREES as a JSON array of 3 numbers. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. " +
            "Example: [45, 0, 30] (sun 45° from zenith, rotated 30° around Z).",
        },
        energy: {
          type: "number",
          description: "Sun light strength. Example: 5.0. Defaults to 5.0.",
        },
        color: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "RGB color as a JSON array of 3 numbers [r, g, b], each 0.0 to 1.0. " +
            "IMPORTANT: Must be a JSON array, NOT a string. " +
            "Example: [1.0, 0.98, 0.95]. Defaults to [1, 1, 1].",
        },
      },
      required: ["rotation"],
    },
    handler: async (args) => {
      const result = await sendToBlender("light/sun-setup", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_light_three_point",
    description:
      "Set up a classic three-point lighting rig around a target position. " +
      "Creates three AREA lights: Key (primary), Fill (softer), and Rim/Back (separation). " +
      "Example call: { \"target\": [0, 0, 1], \"key_energy\": 1000, \"fill_energy\": 400, \"rim_energy\": 600 }. " +
      "Returns the names and positions of all three created lights.",
    inputSchema: {
      type: "object",
      properties: {
        target: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "World-space position the lights point at, as a JSON array of 3 numbers [x, y, z]. " +
            "IMPORTANT: Must be a JSON array, NOT a string. " +
            "Example: [0, 0, 1.0]. Defaults to [0, 0, 0].",
        },
        key_energy: {
          type: "number",
          description: "Energy for the key light in watts. Example: 1000. Defaults to 1000.",
        },
        fill_energy: {
          type: "number",
          description: "Energy for the fill light in watts. Example: 400. Defaults to 400.",
        },
        rim_energy: {
          type: "number",
          description: "Energy for the rim/back light in watts. Example: 600. Defaults to 600.",
        },
      },
      required: [],
    },
    handler: async (args) => {
      const result = await sendToBlender("light/three-point", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_light_hdri_setup",
    description:
      "Set up HDRI image-based environment lighting for the world. " +
      "Loads the specified .hdr or .exr file and wires it through a Background shader node tree. " +
      "Example call: { \"hdri_path\": \"C:/HDRIs/studio.hdr\", \"strength\": 1.5, \"rotation\": 90 }. " +
      "Returns the world name and node configuration details.",
    inputSchema: {
      type: "object",
      properties: {
        hdri_path: {
          type: "string",
          description: "Absolute filesystem path to the HDRI image file (.hdr or .exr). Example: \"C:/HDRIs/studio.hdr\".",
        },
        rotation: {
          type: "number",
          description: "Z-axis rotation offset in degrees for the HDRI. Example: 90. Defaults to 0.",
        },
        strength: {
          type: "number",
          description: "Environment light strength multiplier. Example: 1.5. Defaults to 1.0.",
        },
      },
      required: ["hdri_path"],
    },
    handler: async (args) => {
      const result = await sendToBlender("light/hdri-setup", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_light_world_color",
    description:
      "Set the scene world background to a solid color with uniform strength. " +
      "Useful for ambient fill lighting or a colored backdrop without an HDRI. " +
      "Example call: { \"color\": [0.05, 0.05, 0.1], \"strength\": 1.0 }. " +
      "Returns the world name and the applied color and strength values.",
    inputSchema: {
      type: "object",
      properties: {
        color: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "RGB background color as a JSON array of 3 numbers [r, g, b], each 0.0 to 1.0. " +
            "IMPORTANT: Must be a JSON array, NOT a string. " +
            "Example: [0.05, 0.05, 0.1] (dark blue).",
        },
        strength: {
          type: "number",
          description: "Background light emission strength. Example: 1.0. Defaults to 1.0.",
        },
      },
      required: ["color"],
    },
    handler: async (args) => {
      const result = await sendToBlender("light/world-color", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_light_list",
    description:
      "List all light objects currently in the scene. " +
      "Returns each light's name, type, world-space location, energy, and RGB color.",
    inputSchema: {
      type: "object",
      properties: {},
      required: [],
    },
    handler: async (args) => {
      const result = await sendToBlender("light/list", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_light_shadow_settings",
    description:
      "Configure shadow properties on an existing light. " +
      "Example call: { \"name\": \"KeyLight\", \"params\": { \"use_shadow\": true, \"shadow_soft_size\": 0.5 } }. " +
      "Returns the light name and all applied shadow settings.",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Name of the light object. Example: \"KeyLight\".",
        },
        params: {
          type: "object",
          description:
            "Shadow configuration as a JSON object. " +
            "IMPORTANT: Must be a JSON object, NOT a string. " +
            "Supported keys: use_shadow (boolean), shadow_soft_size (number), " +
            "shadow_buffer_clip_start (number), shadow_cascade_count (integer, SUN only), " +
            "contact_shadow_distance (number). " +
            "Example: { \"use_shadow\": true, \"shadow_soft_size\": 0.5 }.",
        },
      },
      required: ["name", "params"],
    },
    handler: async (args) => {
      const result = await sendToBlender("light/shadow-settings", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
