"""
Python execution handlers for Blender MCP Bridge.
Provides arbitrary Python code execution inside Blender.

WARNING: These handlers execute arbitrary code. Use with caution.
"""

import io
import os
import sys
import traceback
import bpy
from ...utils.response import ok_response, error_response
from .. import register_handler

# Security: allow disabling python exec via environment variable
_PYTHON_EXEC_ALLOWED = os.environ.get("ALLOW_PYTHON_EXEC", "true").lower() != "false"


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _exec_code(code, source_label="<string>"):
    """
    Execute Python code in an isolated namespace with captured stdout/stderr.

    Tries eval() first (for single expressions) to capture the return value.
    Falls back to exec() for multi-line statements.

    Args:
        code (str): Python source to execute.
        source_label (str): Label used in tracebacks (e.g. filename).

    Returns:
        dict with keys: stdout, stderr, result (may be None), error (may be None)
    """
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    # Execution namespace — expose bpy and common modules
    namespace = {
        "__name__": "__blender_mcp__",
        "__file__": source_label,
        "bpy": bpy,
    }

    result_value = None
    exec_error = None

    old_stdout = sys.stdout
    old_stderr = sys.stderr

    try:
        sys.stdout = stdout_buf
        sys.stderr = stderr_buf

        # Try eval first to capture expression results
        try:
            compiled = compile(code.strip(), source_label, "eval")
            result_value = eval(compiled, namespace)  # noqa: S307
        except SyntaxError:
            # Not a single expression — use exec
            try:
                compiled = compile(code, source_label, "exec")
                exec(compiled, namespace)  # noqa: S102
                result_value = namespace.get("result", namespace.get("_result", None))
            except Exception:
                exec_error = traceback.format_exc()
                # Write the traceback to captured stderr as well
                print(exec_error, file=sys.stderr)
        except Exception:
            exec_error = traceback.format_exc()
            print(exec_error, file=sys.stderr)

    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    # Safely serialize result_value
    try:
        # Only include if it's JSON-serialisable; otherwise convert to string
        import json
        json.dumps(result_value)
        serialised_result = result_value
    except (TypeError, ValueError):
        serialised_result = repr(result_value)

    return {
        "stdout": stdout_buf.getvalue(),
        "stderr": stderr_buf.getvalue(),
        "result": serialised_result,
        "error": exec_error,
    }


# ─── Handlers ──────────────────────────────────────────────────────────────────

def _handle_python_exec(params):
    """
    Execute arbitrary Python code in Blender.

    Route: POST /api/python/exec

    Required params:
        code (str): Python source code to execute.

    Returns:
        {stdout, stderr, result, error}
        - stdout: captured standard output
        - stderr: captured standard error
        - result: value of the last expression (if code is a single expression), or None
        - error: traceback string if an exception occurred, or null
    """
    if not _PYTHON_EXEC_ALLOWED:
        return error_response("Python execution is disabled by server configuration (ALLOW_PYTHON_EXEC=false).")
    code = params.get("code")
    if code is None:
        return error_response("Parameter 'code' is required.")
    if not isinstance(code, str):
        return error_response("Parameter 'code' must be a string.")
    if not code.strip():
        return error_response("Parameter 'code' must not be empty.")

    try:
        exec_result = _exec_code(code, source_label="<blender_mcp_exec>")
    except Exception as e:
        return error_response(f"Unexpected error during code execution: {e}")

    return ok_response(exec_result)


def _handle_python_exec_file(params):
    """
    Execute a Python script file in Blender.

    Route: POST /api/python/exec-file

    Required params:
        filepath (str): Absolute path to the .py script file to execute.

    Returns:
        {filepath, stdout, stderr, result, error}
    """
    if not _PYTHON_EXEC_ALLOWED:
        return error_response("Python execution is disabled by server configuration (ALLOW_PYTHON_EXEC=false).")
    filepath = params.get("filepath", "").strip()
    if not filepath:
        return error_response("Parameter 'filepath' is required.")

    if not os.path.isfile(filepath):
        return error_response(f"Script file not found: {filepath}")

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            code = f.read()
    except OSError as e:
        return error_response(f"Failed to read script file: {e}")
    except UnicodeDecodeError as e:
        return error_response(f"Script file is not valid UTF-8: {e}")

    if not code.strip():
        return ok_response({
            "filepath": filepath,
            "stdout": "",
            "stderr": "",
            "result": None,
            "error": None,
            "note": "Script file was empty.",
        })

    try:
        exec_result = _exec_code(code, source_label=filepath)
    except Exception as e:
        return error_response(f"Unexpected error during file execution: {e}")

    return ok_response({
        "filepath": filepath,
        **exec_result,
    })


# ─── Register routes ────────────────────────────────────────────────────────────

register_handler("python", "exec", _handle_python_exec)
register_handler("python", "exec-file", _handle_python_exec_file)
