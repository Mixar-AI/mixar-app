"""
Reference handler for Blender MCP Bridge.
Handles recipe execution from the reference library.
"""

import bpy
from ..utils.response import ok_response, error_response
from . import register_handler


def _handle_execute_recipe(params):
    """Execute a recipe from the reference library. Route: POST /api/reference/execute-recipe"""
    try:
        recipe = params.get("recipe")
        if not recipe:
            return error_response("No recipe data provided")

        scale = params.get("scale", 1.0)
        location = params.get("location", [0, 0, 0])
        name = params.get("name")
        dimensions = params.get("dimensions")

        from ..recipe.executor import RecipeExecutor
        executor = RecipeExecutor(
            recipe,
            scale=scale,
            location=location,
            name=name,
            dimensions=dimensions,
        )
        result = executor.execute()
        return ok_response(result)
    except Exception as e:
        return error_response(f"Recipe execution failed: {e}")


register_handler("reference", "execute-recipe", _handle_execute_recipe)
