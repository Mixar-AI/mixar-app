// Advanced Text object tools — create, edit, set font, and convert text objects

import { sendToBlender } from "../../blender-bridge.js";

export const textObjectTools = [
  {
    name: "blender_text_create",
    description:
      "Create a new Text (font) object in the scene. " +
      "The object is linked to the active collection and made active. " +
      "Optionally set the font file path, size, and world-space location. " +
      "Returns the object name and the text body. " +
      "Example call: { \"text\": \"Hello World\", \"name\": \"Title\", \"location\": [0, 0, 1.5], \"size\": 2.0 }.",
    inputSchema: {
      type: "object",
      properties: {
        text: {
          type: "string",
          description: "The text string to display.",
        },
        name: {
          type: "string",
          description: "Name for the new Text object (default: 'Text').",
        },
        location: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "World-space [x, y, z] location for the object. " +
            "IMPORTANT: Must be a JSON array of 3 numbers, NOT a string. " +
            "Example: [0, 0, 1.5]. Default: [0, 0, 0].",
        },
        font: {
          type: "string",
          description:
            "Absolute path to a .ttf or .otf font file to use. " +
            "If omitted the Blender default font is used.",
        },
        size: {
          type: "number",
          description: "Font size in Blender units (default: 1.0).",
        },
      },
      required: ["text"],
    },
    handler: async (args) => {
      const result = await sendToBlender("text/create", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_text_edit",
    description:
      "Edit properties of an existing Text object. " +
      "All parameters except name are optional — only the supplied values are changed. " +
      "align accepts LEFT, CENTER, RIGHT, or JUSTIFY for horizontal text alignment. " +
      "extrude gives the text depth along Z. " +
      "bevel_depth rounds the extruded edges. " +
      "Returns the updated properties of the text object.",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Name of the Text object to edit.",
        },
        text: {
          type: "string",
          description: "New text body string.",
        },
        font: {
          type: "string",
          description: "Absolute path to a .ttf or .otf font file.",
        },
        size: {
          type: "number",
          description: "Font size in Blender units.",
        },
        extrude: {
          type: "number",
          description: "Extrusion depth along the Z axis in Blender units.",
        },
        bevel_depth: {
          type: "number",
          description: "Bevel depth applied to extruded edges.",
        },
        align: {
          type: "string",
          enum: ["LEFT", "CENTER", "RIGHT", "JUSTIFY"],
          description: "Horizontal text alignment. Must be UPPERCASE.",
        },
      },
      required: ["name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("text/edit", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_text_set_font",
    description:
      "Load a font file and assign it to the specified Text object. " +
      "Supports TrueType (.ttf) and OpenType (.otf) font files. " +
      "The font is loaded into bpy.data.fonts and assigned to the object's curve data. " +
      "Returns the object name and the loaded font name.",
    inputSchema: {
      type: "object",
      properties: {
        text_name: {
          type: "string",
          description: "Name of the Text object to update.",
        },
        font_path: {
          type: "string",
          description: "Absolute filesystem path to the .ttf or .otf font file.",
        },
      },
      required: ["text_name", "font_path"],
    },
    handler: async (args) => {
      const result = await sendToBlender("text/set-font", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_text_to_mesh",
    description:
      "Convert a Text object into a Mesh object. " +
      "The text glyphs are tessellated into polygon geometry. " +
      "The original Text object is replaced by a Mesh object in the scene. " +
      "Returns the name of the resulting mesh object.",
    inputSchema: {
      type: "object",
      properties: {
        text_name: {
          type: "string",
          description: "Name of the Text object to convert.",
        },
      },
      required: ["text_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("text/to-mesh", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_text_to_curve",
    description:
      "Convert a Text object into a Curve object. " +
      "The text glyphs become editable Bezier splines. " +
      "The original Text object is replaced by a Curve object in the scene. " +
      "Returns the name of the resulting curve object.",
    inputSchema: {
      type: "object",
      properties: {
        text_name: {
          type: "string",
          description: "Name of the Text object to convert.",
        },
      },
      required: ["text_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("text/to-curve", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
