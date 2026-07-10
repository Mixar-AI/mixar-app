import { sendToBlender } from "./blender-bridge.js";
import { validateParams } from "./validate-params.js";

const ROUTE_OVERRIDES = {
  blender_render_preview: "viewport/render-preview",
};

// Core tools — always exposed individually
const CORE_TOOLS = new Set([
  // Scene
  "blender_scene_info",
  "blender_scene_list",
  "blender_scene_set_active",

  // Object
  "blender_object_list",
  "blender_object_info",
  "blender_object_create",
  "blender_object_delete",
  "blender_object_transform",
  "blender_object_duplicate",
  "blender_object_select",
  "blender_object_apply_transforms",
  "blender_object_join",
  "blender_object_set_parent",

  // Mesh
  "blender_mesh_create_primitive",
  "blender_mesh_get_data",
  "blender_mesh_set_data",

  // Material
  "blender_material_list",
  "blender_material_create",
  "blender_material_assign",
  "blender_material_get_properties",
  "blender_material_set_property",

  // Modifier
  "blender_modifier_add",
  "blender_modifier_remove",
  "blender_modifier_list",
  "blender_modifier_set_property",
  "blender_modifier_apply",

  // Render
  "blender_render_current",
  "blender_render_get_settings",
  "blender_render_set_settings",

  // Animation
  "blender_anim_insert_keyframe",
  "blender_anim_get_keyframes",
  "blender_anim_set_frame",

  // File
  "blender_file_info",
  "blender_file_save",
  "blender_file_open",

  // Collection
  "blender_collection_list",
  "blender_collection_create",
  "blender_collection_add_object",
  "blender_collection_delete",
  "blender_collection_remove_object",
  "blender_collection_set_visibility",

  // Export / Import
  "blender_export_fbx",
  "blender_export_gltf",
  "blender_import_file",

  // Validation
  "blender_validate_mesh",
  "blender_validate_export_ready",

  // Reference
  "blender_ref_get_dimensions",
  "blender_ref_get_material",
  "blender_ref_execute_recipe",

  // Analysis
  "blender_analyze_mesh",

  // Graphics
  "blender_graphics_capture",

  // Viewport
  "blender_viewport_screenshot",
]);

function toolNameToRoute(toolName) {
  const withoutPrefix = toolName.replace(/^blender_/, "");
  const parts = withoutPrefix.split("_");
  if (parts.length < 2) return null;
  const category = parts[0];
  const action = parts.slice(1).join("-");
  return `${category}/${action}`;
}

export function splitToolTiers(allTools) {
  const core = [];
  const advanced = [];

  for (const tool of allTools) {
    if (CORE_TOOLS.has(tool.name)) {
      core.push(tool);
    } else {
      advanced.push(tool);
    }
  }

  const categories = {};
  for (const t of advanced) {
    const parts = t.name.replace(/^blender_/, "").split("_");
    const cat = parts[0];
    if (!categories[cat]) categories[cat] = [];
    categories[cat].push({ name: t.name, description: t.description, inputSchema: t.inputSchema });
  }

  const advancedMap = new Map();
  for (const t of advanced) {
    advancedMap.set(t.name, t);
  }

  // Meta-tools
  const catalogTool = {
    name: "blender_list_advanced_tools",
    description:
      "List all available advanced/specialized Blender tools organized by category. " +
      "These tools are not directly exposed but can be called via blender_advanced_tool.",
    inputSchema: {
      type: "object",
      properties: {
        category: {
          type: "string",
          description: 'Filter by category name (e.g. "animation", "node", "physics"). Omit for full list.',
        },
      },
    },
    handler: async ({ category } = {}) => {
      if (category) {
        const cat = category.toLowerCase();
        const matching = advanced.filter((t) => {
          const toolCat = t.name.replace(/^blender_/, "").split("_")[0];
          return toolCat === cat;
        });
        if (matching.length === 0) {
          return `No advanced tools found for category "${category}". Available categories: ${Object.keys(categories).join(", ")}`;
        }
        return JSON.stringify(matching.map((t) => ({ name: t.name, description: t.description, inputSchema: t.inputSchema })), null, 2);
      }

      const summary = {};
      for (const [cat, tools] of Object.entries(categories)) {
        summary[cat] = tools.map((t) => t.name);
      }
      return JSON.stringify({
        totalAdvancedTools: advanced.length,
        categories: summary,
      }, null, 2);
    },
  };

  const advancedTool = {
    name: "blender_advanced_tool",
    description:
      "Execute an advanced/specialized Blender tool by name. Use blender_list_advanced_tools " +
      "to discover available tools and their parameters.",
    inputSchema: {
      type: "object",
      properties: {
        tool: {
          type: "string",
          description: 'The tool name to execute (e.g. "blender_node_create", "blender_physics_add")',
        },
        params: {
          type: "object",
          description: "Parameters to pass to the tool.",
          additionalProperties: true,
        },
      },
      required: ["tool"],
    },
    handler: async ({ tool, params } = {}) => {
      if (!tool) {
        return "Error: 'tool' parameter is required. Use blender_list_advanced_tools to see available tools.";
      }

      const targetTool = advancedMap.get(tool);
      if (targetTool) {
        // Apply centralized param validation against the advanced tool's own
        // inputSchema before forwarding — mirrors the pattern used for core
        // tools in the CallToolRequestSchema handler in index.js (line 169).
        const validation = validateParams(targetTool, params || {});
        if (!validation.valid) {
          return `Validation error for "${tool}": ${validation.error}`;
        }
        return await targetTool.handler(params || {});
      }

      // Lazy loading fallback
      const route = ROUTE_OVERRIDES[tool] || toolNameToRoute(tool);
      if (route) {
        try {
          const result = await sendToBlender(route, params || {});
          return JSON.stringify(result, null, 2);
        } catch (err) {
          return `Error executing "${tool}" (route: ${route}): ${err.message}`;
        }
      }

      return `Error: Unknown tool "${tool}". Use blender_list_advanced_tools to see available tools.`;
    },
  };

  return {
    coreTools: core,
    metaTools: [catalogTool, advancedTool],
    advancedCount: advanced.length,
    coreCount: core.length,
  };
}
