// Advanced export/import tools — OBJ, STL, USD exports and reference image import

import { sendToBlender } from "../../blender-bridge.js";

export const exportExtendedTools = [
  {
    name: "blender_export_obj",
    description:
      "Export the scene or selected objects as a Wavefront OBJ file. " +
      "Example call: { \"filepath\": \"C:/Models/scene.obj\", \"selected_only\": false, \"apply_modifiers\": true }. " +
      "Returns the output filepath and file size.",
    inputSchema: {
      type: "object",
      properties: {
        filepath: {
          type: "string",
          description: "Absolute path for the exported .obj file. Example: \"C:/Models/scene.obj\".",
        },
        selected_only: {
          type: "boolean",
          description:
            "Export only selected objects when true. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string. " +
            "Correct: false — Wrong: \"false\". Defaults to false.",
        },
        apply_modifiers: {
          type: "boolean",
          description:
            "Apply mesh modifiers before export when true. " +
            "IMPORTANT: Must be a JSON boolean. Defaults to true.",
        },
        export_materials: {
          type: "boolean",
          description:
            "Export material definitions to a companion .mtl file when true. " +
            "IMPORTANT: Must be a JSON boolean. Defaults to true.",
        },
      },
      required: ["filepath"],
    },
    handler: async (args) => {
      const result = await sendToBlender("export/obj", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_export_stl",
    description:
      "Export the scene or selected objects as an STL file. " +
      "Commonly used for 3D printing workflows. " +
      "Example call: { \"filepath\": \"C:/Models/part.stl\", \"selected_only\": true, \"ascii\": false }. " +
      "Returns the output filepath and file size.",
    inputSchema: {
      type: "object",
      properties: {
        filepath: {
          type: "string",
          description: "Absolute path for the exported .stl file. Example: \"C:/Models/part.stl\".",
        },
        selected_only: {
          type: "boolean",
          description:
            "Export only selected objects when true. " +
            "IMPORTANT: Must be a JSON boolean. Defaults to false.",
        },
        ascii: {
          type: "boolean",
          description:
            "Write ASCII STL instead of binary when true. " +
            "IMPORTANT: Must be a JSON boolean. Defaults to false (binary).",
        },
      },
      required: ["filepath"],
    },
    handler: async (args) => {
      const result = await sendToBlender("export/stl", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_export_usd",
    description:
      "Export the scene or selected objects in Universal Scene Description (USD) format. " +
      "Example call: { \"filepath\": \"C:/Models/scene.usdc\", \"selected_only\": false, \"export_materials\": true }. " +
      "Returns the output filepath and file size.",
    inputSchema: {
      type: "object",
      properties: {
        filepath: {
          type: "string",
          description:
            "Absolute path for the exported USD file (.usd, .usda, or .usdc). " +
            "Example: \"C:/Models/scene.usdc\".",
        },
        format: {
          type: "string",
          enum: ["USD", "USDA", "USDC"],
          description:
            "Override the USD sub-format. Typically inferred from file extension. " +
            "Valid values: \"USD\", \"USDA\", \"USDC\". Example: \"USDC\".",
        },
        selected_only: {
          type: "boolean",
          description:
            "Export only selected objects when true. " +
            "IMPORTANT: Must be a JSON boolean. Defaults to false.",
        },
        export_materials: {
          type: "boolean",
          description:
            "Include material data in the export when true. " +
            "IMPORTANT: Must be a JSON boolean. Defaults to true.",
        },
        export_animation: {
          type: "boolean",
          description:
            "Include animation data in the export when true. " +
            "IMPORTANT: Must be a JSON boolean. Defaults to false.",
        },
      },
      required: ["filepath"],
    },
    handler: async (args) => {
      const result = await sendToBlender("export/usd", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_import_reference_image",
    description:
      "Import an image as a reference/empty image object in the scene. " +
      "Example call: { \"filepath\": \"C:/refs/front_view.png\", \"location\": [0, -5, 1], \"size\": 2.0 }. " +
      "Returns the name and location of the created empty.",
    inputSchema: {
      type: "object",
      properties: {
        filepath: {
          type: "string",
          description: "Absolute path to the image file. Example: \"C:/refs/front_view.png\".",
        },
        location: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "World-space position as a JSON array of 3 numbers [x, y, z]. " +
            "IMPORTANT: Must be a JSON array, NOT a string. " +
            "Example: [0, -5, 1]. Defaults to [0, 0, 0].",
        },
        size: {
          type: "number",
          description: "Display size of the reference image empty. Example: 2.0. Defaults to 1.0.",
        },
      },
      required: ["filepath"],
    },
    handler: async (args) => {
      const result = await sendToBlender("import/reference-image", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
