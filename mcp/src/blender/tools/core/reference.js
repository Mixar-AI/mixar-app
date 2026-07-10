// Reference tools — blender_ref_get_dimensions, blender_ref_get_material, blender_ref_execute_recipe

import { sendToBlender } from "../../blender-bridge.js";
import { findDimension, findMaterial, findRecipe } from "../../reference/loader.js";

export const referenceTools = [
  {
    name: "blender_ref_get_dimensions",
    description:
      "Search real-world dimensions database for accurate measurements for objects " +
      "(furniture, architecture, vehicles, etc.) to ensure realistic 3D modeling. " +
      "Example call: { \"query\": \"dining_table\", \"category\": \"furniture\" }. " +
      "Returns: { count, results: [{ name, category, dimensions: { x, y, z }, unit }] }",
    inputSchema: {
      type: "object",
      properties: {
        query: {
          type: "string",
          description: "Search term. Example: \"dining_table\", \"door\", \"sedan\", \"adult_male\".",
        },
        category: {
          type: "string",
          description:
            "Optional category filter: furniture, architecture, props, weapons, characters, nature, vehicles. " +
            "Example: \"furniture\".",
        },
      },
      required: ["query"],
    },
    handler: async (args) => {
      const result = findDimension(args.query, args.category);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_ref_get_material",
    description:
      "Search PBR material values database for accurate physical material properties " +
      "(base_color, metallic, roughness, etc.) to apply realistic materials. " +
      "Example call: { \"query\": \"brushed_steel\", \"category\": \"metals\" }. " +
      "Returns: { count, results: [{ name, category, base_color, metallic, roughness, specular, ior }] }",
    inputSchema: {
      type: "object",
      properties: {
        query: {
          type: "string",
          description: "Search term. Example: \"brushed_steel\", \"oak\", \"marble_white\", \"clear_glass\".",
        },
        category: {
          type: "string",
          description:
            "Optional category filter: metals, wood, stone, fabric, organic, glass_liquids. " +
            "Example: \"metals\".",
        },
      },
      required: ["query"],
    },
    handler: async (args) => {
      const result = findMaterial(args.query, args.category);
      return JSON.stringify(result, null, 2);
    },
  },

  {
    name: "blender_ref_execute_recipe",
    description:
      "Execute a 3D model recipe from the library. Creates a complete parametric model " +
      "with modifiers and materials in one call. " +
      "Example call: { \"recipe_name\": \"barrel\", \"location\": [2, 0, 0], \"scale\": 1.5, \"name\": \"MyBarrel\" }. " +
      "Returns: { success, object_name, recipe_name, location } or { error, suggestions } if recipe not found.",
    inputSchema: {
      type: "object",
      properties: {
        recipe_name: {
          type: "string",
          description:
            "Name of the recipe to execute. " +
            "Example: \"barrel\", \"column_greek\", \"tree_simple\", \"crate\", \"bolt\".",
        },
        scale: {
          type: "number",
          description: "Uniform scale multiplier applied to the recipe. Example: 1.0. Defaults to 1.0.",
        },
        dimensions: {
          type: "object",
          description:
            "Override specific dimensions of the recipe (in meters). " +
            "IMPORTANT: Must be a JSON object, NOT a string. " +
            "Example: { \"x\": 2.0, \"y\": 1.0, \"z\": 0.8 }.",
          properties: {
            x: { type: "number" },
            y: { type: "number" },
            z: { type: "number" },
          },
        },
        location: {
          type: "array",
          items: { type: "number" },
          minItems: 3,
          maxItems: 3,
          description:
            "World-space placement as a JSON array of exactly 3 numbers [x, y, z]. " +
            "IMPORTANT: Must be a JSON array of numbers, NOT a string. " +
            "Example: [2.0, 0, 0]. Defaults to [0, 0, 0].",
        },
        name: {
          type: "string",
          description: "Optional custom name for the created object. Example: \"MyBarrel\".",
        },
      },
      required: ["recipe_name"],
    },
    handler: async (args) => {
      const recipes = findRecipe(args.recipe_name);
      if (recipes.count === 0) {
        return JSON.stringify({ error: `Recipe not found: ${args.recipe_name}`, suggestions: recipes.suggestions }, null, 2);
      }
      const recipe = recipes.results[0];
      const result = await sendToBlender("reference/execute-recipe", {
        recipe,
        scale: args.scale,
        location: args.location,
        name: args.name,
        dimensions: args.dimensions,
      });
      return JSON.stringify(result, null, 2);
    },
  },
];
