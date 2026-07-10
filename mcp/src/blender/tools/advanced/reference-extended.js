// Advanced reference tools — blender_ref_get_recipe

import { findRecipe } from "../../reference/loader.js";

export const referenceExtendedTools = [
  {
    name: "blender_ref_get_recipe",
    description:
      "Get a 3D model recipe without executing it. Returns the full JSON recipe definition. " +
      "Example call: { \"query\": \"barrel\", \"category\": \"props\" }.",
    inputSchema: {
      type: "object",
      properties: {
        query: {
          type: "string",
          description: "Recipe name to look up, e.g. 'barrel', 'column_greek', 'tree_simple'.",
        },
        category: {
          type: "string",
          description:
            "Optional category filter: hard-surface, architecture, organic, props.",
        },
      },
      required: ["query"],
    },
    handler: async (args) => {
      const result = findRecipe(args.query, args.category);
      return JSON.stringify(result, null, 2);
    },
  },
];
