// Core extended tools — file append/link, scene cleanup, object rename/set-origin,
// modifier reorder, material edit/add-texture/remove

import { sendToBlender } from "../../blender-bridge.js";

export const coreExtendedTools = [
  {
    name: "blender_file_append",
    description:
      "Append a data-block (Object, Material, Mesh, Collection, etc.) from an external .blend file " +
      "into the current scene. The appended data becomes a local copy fully owned by this file. " +
      "filepath is the absolute path to the source .blend file. " +
      "data_type is the data-block category inside the .blend (e.g. 'Object', 'Material', 'Mesh', 'Collection'). " +
      "name is the exact name of the data-block to append. " +
      "Returns the data_type and name that were appended.",
    inputSchema: {
      type: "object",
      properties: {
        filepath: {
          type: "string",
          description: "Absolute path to the source .blend file.",
        },
        data_type: {
          type: "string",
          description:
            "Data-block category to append from (e.g. 'Object', 'Material', 'Mesh', 'Collection').",
        },
        name: {
          type: "string",
          description: "Exact name of the data-block to append from the source file.",
        },
      },
      required: ["filepath", "data_type", "name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("file/append", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_file_link",
    description:
      "Link a data-block (Object, Material, Mesh, Collection, etc.) from an external .blend file " +
      "into the current scene as a library reference. Linked data remains read-only and stays " +
      "connected to the source file. " +
      "filepath is the absolute path to the source .blend file. " +
      "data_type is the data-block category inside the .blend (e.g. 'Object', 'Material', 'Mesh', 'Collection'). " +
      "name is the exact name of the data-block to link. " +
      "Returns the data_type and name that were linked.",
    inputSchema: {
      type: "object",
      properties: {
        filepath: {
          type: "string",
          description: "Absolute path to the source .blend file.",
        },
        data_type: {
          type: "string",
          description:
            "Data-block category to link from (e.g. 'Object', 'Material', 'Mesh', 'Collection').",
        },
        name: {
          type: "string",
          description: "Exact name of the data-block to link from the source file.",
        },
      },
      required: ["filepath", "data_type", "name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("file/link", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_scene_cleanup",
    description:
      "Purge unused (orphaned) data-blocks from the current Blender file to reduce memory usage " +
      "and file size. The optional types array controls which categories are targeted. " +
      "Valid types: 'meshes', 'materials', 'textures', 'all' (default). " +
      "When 'all' is included (or types is omitted), a full recursive orphan-purge is performed. " +
      "Returns the number of data-blocks removed.",
    inputSchema: {
      type: "object",
      properties: {
        types: {
          type: "array",
          items: {
            type: "string",
            enum: ["meshes", "materials", "textures", "all"],
          },
          description:
            "List of data types to purge. " +
            "IMPORTANT: Must be a JSON array of strings, NOT a string. " +
            "Example: [\"meshes\", \"materials\"]. Defaults to [\"all\"] which removes all orphaned data.",
        },
      },
    },
    handler: async (args) => {
      const result = await sendToBlender("scene/cleanup", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_object_rename",
    description:
      "Rename an existing object in the scene. " +
      "old_name must exactly match the current name of the object. " +
      "new_name is the desired name; if another object already has that name Blender will " +
      "automatically suffix the name with '.001' (or similar) to keep names unique. " +
      "Returns the old_name and the actual new_name assigned by Blender.",
    inputSchema: {
      type: "object",
      properties: {
        old_name: {
          type: "string",
          description: "Current exact name of the object to rename.",
        },
        new_name: {
          type: "string",
          description: "Desired new name for the object.",
        },
      },
      required: ["old_name", "new_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("object/rename", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_object_set_origin",
    description:
      "Set the origin point of an object. The origin is the pivot point that defines " +
      "the object's local coordinate system and appears as the orange dot in the viewport. " +
      "CENTER — moves the origin to the center of mass of the geometry. " +
      "GEOMETRY — moves the geometry so the origin stays at the world position but the mesh shifts. " +
      "CURSOR — moves the origin to the current 3D cursor location. " +
      "BOTTOM — moves the origin to the bottom-center of the object's bounding box " +
      "(useful for placing objects flush on a surface). " +
      "Accepts both 'object_name' and 'name' parameters. " +
      "Returns the object name and the type of origin set applied.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object whose origin will be set. Example: \"Cube\".",
        },
        name: {
          type: "string",
          description:
            "Alias for object_name (backward compatibility). Prefer object_name for new calls.",
        },
        type: {
          type: "string",
          enum: ["CENTER", "BOTTOM", "CURSOR", "GEOMETRY"],
          description:
            "Origin type. Must be UPPERCASE. CENTER (center of mass), BOTTOM (bottom of bounding box), " +
            "CURSOR (3D cursor location), or GEOMETRY (move geometry to origin).",
        },
      },
      required: [],
    },
    handler: async (args) => {
      const resolved = { ...args, object_name: args.object_name || args.name };
      if (!resolved.object_name) {
        return JSON.stringify({ error: "Either 'object_name' or 'name' is required." });
      }
      const result = await sendToBlender("object/set-origin", resolved);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_modifier_reorder",
    description:
      "Change the position of a modifier in an object's modifier stack. " +
      "Modifiers are evaluated top-to-bottom, so order can significantly affect the result. " +
      "Provide either direction ('UP' to move one step toward the top, 'DOWN' toward the bottom) " +
      "or index (a zero-based integer for the desired final position in the stack). " +
      "On Blender 4.x, index-based reordering uses the native modifiers.move() API. " +
      "On Blender 3.x, direction-based movement uses modifier_move_up/down operators. " +
      "Returns the object name, modifier name, and resulting index.",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "Name of the object that owns the modifier.",
        },
        modifier_name: {
          type: "string",
          description: "Name of the modifier to reorder.",
        },
        direction: {
          type: "string",
          enum: ["UP", "DOWN"],
          description:
            "Move the modifier one step UP (toward top of stack) or DOWN (toward bottom). Must be UPPERCASE. " +
            "Use either direction or index, not both.",
        },
        index: {
          type: "integer",
          minimum: 0,
          description:
            "Zero-based target index for the modifier in the stack. " +
            "Use either index or direction, not both.",
        },
      },
      required: ["object_name", "modifier_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("modifier/reorder", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_material_edit",
    description:
      "Edit Principled BSDF shader inputs on an existing material by name. " +
      "The material must use nodes and contain a Principled BSDF node. " +
      "properties is a key-value object where each key is a Principled BSDF input name " +
      "(e.g. 'Base Color', 'Roughness', 'Metallic', 'Emission Color', 'Alpha') and " +
      "each value is the new default_value (use an array of 3 or 4 floats for color inputs, " +
      "a scalar for numeric inputs). Input names are automatically mapped between Blender 3.x " +
      "and 4.x versions. Returns the material name and list of changed inputs.",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Name of the material to edit.",
        },
        properties: {
          type: "object",
          description:
            "Key-value pairs of Principled BSDF input names to new values. " +
            "IMPORTANT: Must be a JSON object, NOT a string. " +
            "Examples: { \"Roughness\": 0.5 }, { \"Base Color\": [1, 0, 0, 1] }.",
        },
      },
      required: ["name", "properties"],
    },
    handler: async (args) => {
      const result = await sendToBlender("material/edit", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_material_add_texture",
    description:
      "Load an image file and connect it as a texture to a specific Principled BSDF channel " +
      "in an existing material. The material must use nodes. " +
      "An Image Texture node is created, the image is loaded from image_path, and its output " +
      "is wired to the specified channel. " +
      "For the 'Normal' channel a Normal Map node is automatically inserted between the texture " +
      "and the Principled BSDF, and the image colorspace is set to 'Non-Color'. " +
      "channel accepts canonical Principled BSDF input names such as 'Base Color', 'Roughness', " +
      "'Metallic', 'Normal', 'Emission Color', etc. " +
      "This tool creates Image Texture nodes only. For procedural textures (Noise, Wave, Voronoi, Musgrave, etc.), use blender_node_add instead. " +
      "Returns the material name, channel, and image name.",
    inputSchema: {
      type: "object",
      properties: {
        material_name: {
          type: "string",
          description: "Name of the material to add the texture to.",
        },
        channel: {
          type: "string",
          description:
            "Principled BSDF input channel to connect the texture to, " +
            "e.g. 'Base Color', 'Roughness', 'Metallic', 'Normal', 'Emission Color'.",
        },
        image_path: {
          type: "string",
          description: "Absolute path to the image file to load as a texture.",
        },
      },
      required: ["material_name", "channel", "image_path"],
    },
    handler: async (args) => {
      const result = await sendToBlender("material/add-texture", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_material_remove",
    description:
      "Permanently remove a material data-block from the Blender file by name. " +
      "Any objects that referenced this material will have the slot cleared. " +
      "This action cannot be undone via the MCP bridge. " +
      "Returns the name of the material that was removed.",
    inputSchema: {
      type: "object",
      properties: {
        name: {
          type: "string",
          description: "Name of the material to remove.",
        },
      },
      required: ["name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("material/remove", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_object_set_visibility",
    description:
      "Set visibility properties of an object: hide_viewport (3D viewport), " +
      "hide_render (final renders), hide_select (prevent selection). " +
      "Only the provided properties are changed; omitted ones are left unchanged. " +
      "Example call: { \"object_name\": \"Cube\", \"hide_viewport\": true, \"hide_render\": true }. " +
      "Returns: { object_name, hide_viewport, hide_render, hide_select }",
    inputSchema: {
      type: "object",
      properties: {
        object_name: {
          type: "string",
          description: "The exact name of the object. Example: \"Cube\".",
        },
        hide_viewport: {
          type: "boolean",
          description:
            "Hide/show object in the viewport. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string.",
        },
        hide_render: {
          type: "boolean",
          description:
            "Hide/show object in final renders. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string.",
        },
        hide_select: {
          type: "boolean",
          description:
            "Make object non-selectable in the viewport. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string.",
        },
      },
      required: ["object_name"],
    },
    handler: async (args) => {
      const result = await sendToBlender("object/set-visibility", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
