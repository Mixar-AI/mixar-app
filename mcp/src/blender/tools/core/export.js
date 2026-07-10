// Export/Import tools — blender_export_fbx, blender_export_gltf, blender_import_file

import { sendToBlender } from "../../blender-bridge.js";

export const exportTools = [
  {
    name: "blender_export_fbx",
    description:
      "Export the current scene or selected objects as an FBX file. " +
      "Supports engine presets for Unity, Unreal Engine, or a generic target. " +
      "The parent directories of filepath are NOT created automatically — ensure the folder exists. " +
      "Example call: { \"filepath\": \"C:/Models/table.fbx\", \"target_engine\": \"UNITY\", \"selected_only\": false, \"apply_modifiers\": true }. " +
      "Returns: { success, filepath, file_size_bytes, size_readable, target_engine }",
    inputSchema: {
      type: "object",
      properties: {
        filepath: {
          type: "string",
          description:
            "Absolute path for the exported .fbx file. The directory must already exist. " +
            "Example: \"C:/Projects/MyGame/Assets/Models/table.fbx\".",
        },
        selected_only: {
          type: "boolean",
          description:
            "Export only selected objects when true, or the full scene when false. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string. " +
            "Correct: false — Wrong: \"false\". Defaults to false.",
        },
        apply_modifiers: {
          type: "boolean",
          description:
            "Apply mesh modifiers before export when true. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string. " +
            "Correct: true — Wrong: \"true\". Defaults to true.",
        },
        forward_axis: {
          type: "string",
          enum: ["-Z", "Y", "X", "-Y", "Z", "-X"],
          description:
            "Forward axis for the export coordinate system. " +
            "Valid values: \"-Z\", \"Y\", \"X\", \"-Y\", \"Z\", \"-X\". " +
            "Overridden by target_engine presets. Example: \"-Z\".",
        },
        up_axis: {
          type: "string",
          enum: ["Y", "Z", "X", "-Y", "-Z", "-X"],
          description:
            "Up axis for the export coordinate system. " +
            "Valid values: \"Y\", \"Z\", \"X\", \"-Y\", \"-Z\", \"-X\". " +
            "Overridden by target_engine presets. Example: \"Y\".",
        },
        global_scale: {
          type: "number",
          description:
            "Global scale factor applied during export. " +
            "Example: 1.0 (no scaling). Defaults to 1.0.",
        },
        embed_textures: {
          type: "boolean",
          description:
            "Embed texture files inside the FBX when true. " +
            "IMPORTANT: Must be a JSON boolean. Defaults to false.",
        },
        target_engine: {
          type: "string",
          enum: ["UNITY", "UNREAL", "GENERIC"],
          description:
            "Engine preset that overrides axis and scale settings. Must be UPPERCASE. " +
            "UNITY: forward=-Z, up=Y, scale=1, bake_space_transform=true. " +
            "UNREAL: forward=X, up=Z. " +
            "GENERIC: no preset applied (uses forward_axis/up_axis params). " +
            "Example: \"UNITY\". Defaults to \"GENERIC\".",
        },
        exclude_types: {
          type: "array",
          items: { type: "string" },
          description:
            "Object types to exclude from export (e.g. CAMERA, LIGHT). " +
            "IMPORTANT: Must be a JSON array of UPPERCASE strings. " +
            "Example: [\"CAMERA\", \"LIGHT\"]. When provided, only non-excluded objects are exported.",
        },
      },
      required: ["filepath"],
    },
    handler: async (args) => {
      const result = await sendToBlender("export/fbx", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_export_gltf",
    description:
      "Export the current scene or selected objects as a glTF or GLB file. " +
      "Supports GLB (binary), GLTF_SEPARATE (with external textures), and " +
      "GLTF_EMBEDDED (textures embedded in JSON). Optionally applies Draco mesh compression. " +
      "Example call: { \"filepath\": \"C:/Models/scene.glb\", \"format\": \"GLB\", \"selected_only\": false }. " +
      "Returns: { success, filepath, format, draco_compression, file_size_bytes, size_readable }",
    inputSchema: {
      type: "object",
      properties: {
        filepath: {
          type: "string",
          description:
            "Absolute path for the exported file (extension may be .glb or .gltf). " +
            "Example: \"C:/Models/scene.glb\".",
        },
        format: {
          type: "string",
          enum: ["GLB", "GLTF_SEPARATE", "GLTF_EMBEDDED"],
          description:
            "Output format. Must be UPPERCASE. " +
            "GLB = single binary file, GLTF_SEPARATE = JSON + external .bin + textures, " +
            "GLTF_EMBEDDED = JSON with embedded base64 textures. " +
            "Example: \"GLB\". Defaults to \"GLB\".",
        },
        selected_only: {
          type: "boolean",
          description:
            "Export only selected objects when true. " +
            "IMPORTANT: Must be a JSON boolean (true or false), NOT a string. " +
            "Defaults to false.",
        },
        apply_modifiers: {
          type: "boolean",
          description:
            "Apply mesh modifiers before export when true. " +
            "IMPORTANT: Must be a JSON boolean. Defaults to true.",
        },
        export_draco: {
          type: "boolean",
          description:
            "Enable Draco mesh compression when true. Reduces file size significantly. " +
            "IMPORTANT: Must be a JSON boolean. Defaults to false.",
        },
        draco_compression_level: {
          type: "integer",
          minimum: 0,
          maximum: 10,
          description:
            "Draco compression level. 0 = fastest/lowest compression, 10 = slowest/highest. " +
            "Example: 6. Defaults to 6.",
        },
      },
      required: ["filepath"],
    },
    handler: async (args) => {
      const result = await sendToBlender("export/gltf", args);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_import_file",
    description:
      "Import a 3D file into the current Blender scene. " +
      "Supported formats: FBX (.fbx), glTF/GLB (.gltf, .glb), OBJ (.obj), STL (.stl). " +
      "Format is auto-detected from the file extension unless explicitly provided. " +
      "Example call: { \"filepath\": \"C:/Models/character.fbx\" }. " +
      "Returns: { success, filepath, format, imported_objects: [{name, type}], imported_count }",
    inputSchema: {
      type: "object",
      properties: {
        filepath: {
          type: "string",
          description:
            "Absolute path to the 3D file to import. " +
            "Example: \"C:/Models/character.fbx\".",
        },
        format: {
          type: "string",
          description:
            "Force a specific import format. Valid values: \"fbx\", \"gltf\", \"obj\", \"stl\". " +
            "If omitted, format is auto-detected from the file extension.",
        },
      },
      required: ["filepath"],
    },
    handler: async (args) => {
      const result = await sendToBlender("import/file", args);
      return JSON.stringify(result, null, 2);
    },
  },
];
