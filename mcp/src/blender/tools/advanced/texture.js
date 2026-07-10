// Advanced texture tools — create, open, bake, paint, save, pack, channel-pack, resize, invert, validate, list

import { sendToBlender } from "../../blender-bridge.js";

export const textureTools = [
  {
    name: "blender_texture_create_image",
    description:
      "Create a new blank image in Blender's image data-block. " +
      "Specify the name, width, and height in pixels. " +
      "Optionally set a base fill color as [R, G, B, A], enable an alpha channel, " +
      "or use a 32-bit float buffer for HDR/EXR work. " +
      "Returns the new image name and its dimensions. " +
      "Example call: { \"name\": \"Diffuse\", \"width\": 2048, \"height\": 2048, \"color\": [0.5, 0.5, 0.5, 1.0] }.",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Name for the new image data-block.",
        },
        width: {
          type: "integer",
          description: "Image width in pixels (e.g. 1024, 2048, 4096).",
        },
        height: {
          type: "integer",
          description: "Image height in pixels (e.g. 1024, 2048, 4096).",
        },
        color: {
          type: "array",
          items: { type: "number" },
          minItems: 4,
          maxItems: 4,
          description:
            "Optional RGBA fill color as [R, G, B, A] in 0-1 range. " +
            "IMPORTANT: Must be a JSON array of 4 numbers, NOT a string. " +
            "Example: [0.5, 0.5, 0.5, 1.0]. Defaults to black transparent.",
        },
        alpha: {
          type: "boolean",
          description:
            "Whether the image should have an alpha channel. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string. Defaults to true.",
        },
        float: {
          type: "boolean",
          description:
            "Use a 32-bit float buffer instead of 8-bit. Useful for HDR or normal maps. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string. Defaults to false.",
        },
      },
      required: ["name", "width", "height"],
    },
    handler: async (args) => {
      const result = await sendToBlender("texture/create-image", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_texture_open_image",
    description:
      "Load an image from disk into Blender's image data-blocks. " +
      "Supports all formats Blender can read (PNG, JPEG, EXR, HDR, TIFF, etc.). " +
      "Optionally rename the image after loading. " +
      "Returns the image name, dimensions, and detected color space.",
    inputSchema: {
      type: "object",
      properties: {
        filepath: {
          type: "string",
          description: "Absolute path to the image file on disk.",
        },
        name: {
          type: "string",
          description: "Optional name to assign to the image data-block after loading.",
        },
      },
      required: ["filepath"],
    },
    handler: async (args) => {
      const result = await sendToBlender("texture/open-image", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_texture_bake",
    description:
      "Bake a texture map from the active object using Cycles. " +
      "Switches the render engine to Cycles, creates a bake target image, " +
      "sets it as the active Image Texture node in the object's material, " +
      "then runs the bake. Supported bake types: DIFFUSE, NORMAL, ROUGHNESS, AO, EMIT, COMBINED. " +
      "Returns the baked image name.",
    inputSchema: {
      type: "object",
      properties: {
        type: {
          type: "string",
          enum: ["DIFFUSE", "NORMAL", "ROUGHNESS", "AO", "EMIT", "COMBINED"],
          description: "The type of bake pass to produce. Must be UPPERCASE.",
        },
        object_name: {
          type: "string",
          description: "Name of the mesh object to bake from.",
        },
        resolution: {
          type: "integer",
          maximum: 8192,
          description: "Bake image resolution in pixels (square). Defaults to 1024.",
        },
        margin: {
          type: "integer",
          description: "UV island margin in pixels to prevent seam bleeding. Defaults to 16.",
        },
      },
      required: ["type", "object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("texture/bake", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_texture_bake_from_highpoly",
    description:
      "Bake a texture map from a high-poly source mesh onto a low-poly target mesh " +
      "using Cycles' Selected-to-Active bake mode. " +
      "The high-poly and low-poly objects must overlap in world space. " +
      "A cage extrusion distance can be set to improve projection accuracy. " +
      "Returns the baked image name.",
    inputSchema: {
      type: "object",
      properties: {
        highpoly_name: {
          type: "string",
          description: "Name of the high-poly source object.",
        },
        lowpoly_name: {
          type: "string",
          description: "Name of the low-poly target object that will receive the baked map.",
        },
        type: {
          type: "string",
          enum: ["DIFFUSE", "NORMAL", "ROUGHNESS", "AO", "EMIT", "COMBINED"],
          description: "The type of bake pass to produce. Must be UPPERCASE.",
        },
        cage_extrusion: {
          type: "number",
          description: "Cage extrusion distance in Blender units for ray projection. Defaults to 0.1.",
        },
        resolution: {
          type: "integer",
          maximum: 8192,
          description: "Bake image resolution in pixels (square). Defaults to 1024.",
        },
      },
      required: ["highpoly_name", "lowpoly_name", "type"],
    },
    handler: async (args) => {
      const result = await sendToBlender("texture/bake-from-highpoly", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_texture_paint_solid",
    description:
      "Fill an image texture with a solid RGBA color. " +
      "If no face list is provided the entire image is flood-filled. " +
      "Face-specific painting uses UV coordinates to restrict the fill to the listed face indices. " +
      "Returns the image name and the number of pixels modified.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the mesh object whose UV layout is used for face painting.",
        },
        image_name: {
          type: "string",
          description: "Name of the image data-block to paint into.",
        },
        color: {
          type: "array",
          items: { type: "number" },
          minItems: 4,
          maxItems: 4,
          description:
            "RGBA fill color as [R, G, B, A] in 0-1 range. " +
            "IMPORTANT: Must be a JSON array of 4 numbers, NOT a string. " +
            "Example: [1.0, 0.0, 0.0, 1.0] (opaque red).",
        },
        faces: {
          type: "array",
          items: { type: "integer" },
          description:
            "Optional list of face indices to restrict painting. " +
            "IMPORTANT: Must be a JSON array of integers, NOT a string. " +
            "Example: [0, 1, 5, 12]. Omit to fill the whole image.",
        },
      },
      required: ["object_name", "image_name", "color"],
    },
    handler: async (args) => {
      const result = await sendToBlender("texture/paint-solid", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_texture_save",
    description:
      "Save an image data-block to disk. " +
      "If filepath is omitted the image is saved to its existing path. " +
      "format controls the output file type (PNG, JPEG, OPEN_EXR, TIFF, etc.). " +
      "Returns the filepath written and file size.",
    inputSchema: {
      type: "object",
      properties: {
        image_name: {
          type: "string",
          description: "Name of the image data-block to save.",
        },
        filepath: {
          type: "string",
          description: "Absolute destination path on disk. Uses the image's existing path if omitted.",
        },
        format: {
          type: "string",
          description: "Output file format, e.g. 'PNG', 'JPEG', 'OPEN_EXR', 'TIFF'. Defaults to 'PNG'.",
        },
      },
      required: ["image_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("texture/save", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_texture_pack",
    description:
      "Pack one or all images into the .blend file so the project is self-contained. " +
      "If image_name is provided only that image is packed; if omitted all images are packed. " +
      "Returns the list of images that were packed.",
    inputSchema: {
      type: "object",
      properties: {
        image_name: {
          type: "string",
          description: "Name of a specific image to pack. Omit to pack every image in the scene.",
        },
      },
      required: [],
    },
    handler: async (args) => {
      const result = await sendToBlender("texture/pack", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_texture_channel_pack",
    description:
      "Create a new image by copying individual channels from up to four source images. " +
      "Useful for packing ORM (Occlusion/Roughness/Metallic) maps or similar channel-packed textures. " +
      "Each source is specified as 'image_name:channel' where channel is R, G, B, or A. " +
      "Returns the output image name and dimensions.",
    inputSchema: {
      type: "object",
      properties: {
        output_name: {
          type: "string",
          description: "Name for the newly created packed image.",
        },
        r_source: {
          type: "string",
          description: "Source for the Red channel as 'image_name:R|G|B|A'.",
        },
        g_source: {
          type: "string",
          description: "Source for the Green channel as 'image_name:R|G|B|A'.",
        },
        b_source: {
          type: "string",
          description: "Source for the Blue channel as 'image_name:R|G|B|A'.",
        },
        a_source: {
          type: "string",
          description: "Optional source for the Alpha channel as 'image_name:R|G|B|A'. Defaults to fully opaque (1.0).",
        },
      },
      required: ["output_name", "r_source", "g_source", "b_source"],
    },
    handler: async (args) => {
      const result = await sendToBlender("texture/channel-pack", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_texture_resize",
    description:
      "Resize an existing image data-block to new pixel dimensions. " +
      "The operation is performed in-place using Blender's built-in scaling. " +
      "Returns the image name and the new dimensions.",
    inputSchema: {
      type: "object",
      properties: {
        image_name: {
          type: "string",
          description: "Name of the image data-block to resize.",
        },
        width: {
          type: "integer",
          description: "Target width in pixels.",
        },
        height: {
          type: "integer",
          description: "Target height in pixels.",
        },
      },
      required: ["image_name", "width", "height"],
    },
    handler: async (args) => {
      const result = await sendToBlender("texture/resize", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_texture_roughness_to_smoothness",
    description:
      "Invert a roughness map to produce a smoothness (glossiness) map by computing 1.0 − value " +
      "for every RGB pixel while leaving the alpha channel unchanged. " +
      "Produces a new image or overwrites in-place when output_name is omitted. " +
      "Returns the output image name.",
    inputSchema: {
      type: "object",
      properties: {
        image_name: {
          type: "string",
          description: "Name of the source roughness image.",
        },
        output_name: {
          type: "string",
          description: "Name for the output smoothness image. If omitted the source image is modified in-place.",
        },
      },
      required: ["image_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("texture/roughness-to-smoothness", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_texture_colorspace_validate",
    description:
      "Scan Image Texture nodes in materials and report color-space mismatches. " +
      "PBR convention: textures connected to a Color input should use 'sRGB'; " +
      "data maps (Normal, Roughness, Metallic, AO, etc.) should use 'Non-Color'. " +
      "Optionally restrict the scan to a single object's materials. " +
      "Returns a list of mismatches with suggested corrections.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of an object whose materials to validate. Omit to scan every material in the scene.",
        },
      },
      required: [],
    },
    handler: async (args) => {
      const result = await sendToBlender("texture/colorspace-validate", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_texture_list",
    description:
      "List all image data-blocks currently loaded in the Blender session. " +
      "Returns name, pixel dimensions, source filepath, color space, dirty (unsaved changes) flag, " +
      "and whether the image has pixel data in memory.",
    inputSchema: {
      type: "object",
      properties: {},
      required: [],
    },
    handler: async (args) => {
      const result = await sendToBlender("texture/list", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
