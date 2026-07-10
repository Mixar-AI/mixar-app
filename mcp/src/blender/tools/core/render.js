// Render tools — blender_render_current, blender_render_get_settings, blender_render_set_settings

import { sendToBlender } from "../../blender-bridge.js";

export const renderTools = [
  {
    name: "blender_render_current",
    description:
      "Render the current frame in Blender and write the result to disk. " +
      "Optionally override the output path and file format. " +
      "WARNING: This operation is blocking — it may take several seconds to complete. " +
      "Example call: { \"output_path\": \"C:/renders/frame_001.png\", \"file_format\": \"PNG\" }. " +
      "Returns: { output_path, file_format, resolution: [width, height], render_time_seconds }",
    inputSchema: {
      type: "object",
      properties: {
        output_path: {
          type: "string",
          description:
            "File path to write the rendered image to. " +
            "Example: \"C:/renders/frame_001.png\". " +
            "Omit to use the path already configured in Blender's render settings.",
        },
        file_format: {
          type: "string",
          enum: ["PNG", "JPEG", "EXR", "OPEN_EXR", "TIFF", "BMP"],
          description:
            "Image format for the rendered output. Must be UPPERCASE. " +
            "Example: \"PNG\". Omit to use the format already configured in Blender.",
        },
      },
    },
    handler: async (args) => {
      const result = await sendToBlender("render/current", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_render_get_settings",
    description:
      "Read the current render settings from the active Blender scene: engine, resolution, " +
      "sample count, output path, file format, frame range, and color management settings. " +
      "Returns: { engine, resolution_x, resolution_y, resolution_percentage, samples, output_path, file_format, frame_start, frame_end, color_management }",
    inputSchema: {
      type: "object",
      properties: {},
    },
    handler: async (args) => {
      const result = await sendToBlender("render/get-settings", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_render_set_settings",
    description:
      "Update one or more render settings on the active Blender scene. " +
      "All parameters are optional — only the provided ones will be changed. " +
      "Example call: { \"engine\": \"CYCLES\", \"resolution_x\": 1920, \"resolution_y\": 1080, \"samples\": 128 }. " +
      "Returns: { engine, resolution_x, resolution_y, resolution_percentage, samples, output_path, file_format, frame_start, frame_end, frame_current, color_management }",
    inputSchema: {
      type: "object",
      properties: {
        engine: {
          type: "string",
          enum: ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES", "BLENDER_WORKBENCH"],
          description:
            "Render engine to use. Must be UPPERCASE and exactly one of the enum values. " +
            "BLENDER_EEVEE: EEVEE (Blender 3.x and 5.0+). " +
            "BLENDER_EEVEE_NEXT: EEVEE Next (Blender 4.x). " +
            "CYCLES: photorealistic path tracer. " +
            "BLENDER_WORKBENCH: lightweight viewport renderer. " +
            "Example: \"CYCLES\".",
        },
        resolution_x: {
          type: "integer",
          maximum: 8192,
          description: "Horizontal resolution in pixels. Example: 1920.",
        },
        resolution_y: {
          type: "integer",
          maximum: 8192,
          description: "Vertical resolution in pixels. Example: 1080.",
        },
        resolution_percentage: {
          type: "integer",
          description:
            "Resolution scale percentage (1–100). " +
            "The actual render resolution is resolution_x/y × this percentage. Example: 100.",
        },
        samples: {
          type: "integer",
          maximum: 10000,
          description:
            "Number of render samples. Higher = better quality but slower. " +
            "Example: 128 (Cycles) or 64 (EEVEE).",
        },
        output_path: {
          type: "string",
          description: "File system path where rendered images will be saved. Example: \"C:/renders/\".",
        },
        file_format: {
          type: "string",
          enum: ["PNG", "JPEG", "EXR", "OPEN_EXR", "TIFF", "BMP"],
          description: "Output image file format. Must be UPPERCASE. Example: \"PNG\".",
        },
        frame_start: {
          type: "integer",
          description: "First frame of the animation range. Example: 1.",
        },
        frame_end: {
          type: "integer",
          description: "Last frame of the animation range. Example: 250.",
        },
      },
    },
    handler: async (args) => {
      const result = await sendToBlender("render/set-settings", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
