"""
Standard response helpers for Blender MCP Bridge.
All handlers should use these to ensure consistent response format.
"""

import os


def coerce_value(current_value, new_value):
    """
    Coerce new_value to match the type of current_value.

    Handles the common MCP case where JSON values arrive as strings even when
    the target attribute expects int, float, or bool.  Lists/tuples are
    coerced element-by-element using the type of the first element in
    current_value (covers colour/vector attributes).
    """
    if not isinstance(new_value, str):
        # Already the right kind of Python object; nothing to do.
        return new_value

    target_type = type(current_value)

    if target_type == bool:
        return new_value.lower() in ("true", "1", "yes")
    if target_type == int:
        return int(float(new_value))  # "2.0" → 2 as well as "2"
    if target_type == float:
        return float(new_value)

    # Sequence types (Color, Vector, …): coerce to a plain list
    if isinstance(current_value, (list, tuple)) or (hasattr(current_value, "__len__") and not isinstance(current_value, str)):
        try:
            elem_type = type(current_value[0]) if len(current_value) > 0 else float
            return [elem_type(v) for v in new_value.strip("[]()").split(",")]
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"Failed to parse '{new_value}' as a sequence of "
                f"{elem_type.__name__}: {e}"
            )

    # Fallback: return as-is (str target or unknown type)
    return new_value


def ok_response(data):
    """Return a success response."""
    return {"success": True, "data": data}


def error_response(message, code=None):
    """Return an error response."""
    result = {"success": False, "error": str(message)}
    if code is not None:
        result["code"] = code
    return result


def not_found(name, entity_type="Object"):
    """Return a not-found error response."""
    return {"success": False, "error": f"{entity_type} '{name}' not found"}


def validate_filepath(filepath, must_exist=False):
    """
    Validate a file path for safety.

    Checks:
    - No null bytes (can bypass security checks in some runtimes)
    - Path is absolute (prevents relative path ambiguity)
    - No '..' traversal components
    - Optionally, file must already exist on disk

    Args:
        filepath: The file path string to validate.
        must_exist: If True, also verify the file exists on disk.

    Returns:
        (resolved_path, None) on success, or (None, error_string) on failure.
    """
    if not filepath or not isinstance(filepath, str):
        return None, "filepath is required and must be a non-empty string."

    # Null byte injection
    if "\x00" in filepath:
        return None, "filepath contains null bytes."

    # Must be absolute
    if not os.path.isabs(filepath):
        return None, (
            f"filepath must be an absolute path, got: {filepath!r}. "
            "Provide a full path like 'C:/Projects/scene.blend' or '/home/user/scene.blend'."
        )

    # Reject path traversal via '..' components
    # Normalize first so 'C:/foo/bar/../baz' becomes 'C:/foo/baz'
    normalized = os.path.normpath(filepath)
    # After normpath, '..' should not remain unless escaping root
    parts = normalized.replace("\\", "/").split("/")
    if ".." in parts:
        return None, f"filepath contains path traversal (..) components: {filepath!r}"

    if must_exist and not os.path.exists(normalized):
        return None, f"File not found: {filepath}"

    return normalized, None
