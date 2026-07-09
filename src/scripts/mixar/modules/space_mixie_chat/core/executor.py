# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Safe script executor for running generated bpy scripts.

This module provides functionality to safely execute Python/Blender
scripts, capture output, detect changes, and handle errors.
"""

from mixar.config.logging_config import get_logger
import ast
import builtins
import json
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from io import StringIO
from typing import Any, Optional

import bpy

from ..constants import SCRIPT_TIMEOUT_THRESHOLD

logger = get_logger(__name__)


class SandboxViolationError(RuntimeError):
    """Raised when a script fails AST sandbox validation."""
    pass


# Restricted module wrappers (see sandbox_modules.py for implementation)
from .sandbox_modules import (
    RESTRICTED_BASE64,
    RESTRICTED_TEMPFILE,
    RESTRICTED_URLLIB,
    restricted_open,
)
from .sandbox_builtins import get_safe_builtins, sanitize_value
from .sandbox_validator import validate_script_ast
from .sandbox_transform import snapshot_collection_iterations


@dataclass
class ExecutionResult:
    """Result of script execution."""

    success: bool
    output: str = ""
    error: Optional[str] = None
    traceback: Optional[str] = None

    # Changes detected
    created_objects: list[str] = field(default_factory=list)
    modified_objects: list[str] = field(default_factory=list)
    deleted_objects: list[str] = field(default_factory=list)

    # Return value if script returned something
    return_value: Any = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON-RPC response.

        Returns a response with `success` at the top level.
        If __RESULT__ was set in the script and is a dict, its contents
        are flattened into the response.
        """
        response = {
            "success": self.success,
        }

        # Flatten return_value dict into response (for __RESULT__ data)
        if self.return_value and isinstance(self.return_value, dict):
            sanitized = sanitize_value(self.return_value)
            if isinstance(sanitized, dict):
                response.update(sanitized)
        elif self.return_value is not None:
            response["return_value"] = sanitize_value(self.return_value)

        # Include metadata only if present
        if self.output:
            response["output"] = self.output
        if self.created_objects:
            response["created_objects"] = self.created_objects
        if self.modified_objects:
            response["modified_objects"] = self.modified_objects
        if self.deleted_objects:
            response["deleted_objects"] = self.deleted_objects
        if self.error:
            response["error"] = self.error
        # Forward the traceback over the (internal) RPC so the backend can log the
        # failing line. This is an internal channel; the backend strips tracebacks
        # from any client-facing API response per its own contract.
        if self.traceback:
            response["traceback"] = self.traceback

        return response


class ScriptExecutor:
    """
    Safely executes generated bpy scripts.

    Features:
    - Captures stdout/stderr
    - Detects scene changes (created/modified/deleted objects)
    - Handles errors gracefully
    - Integrates with Blender's undo system
    - Cleans up bpy.app.handlers installed by scripts
    - Hardened sandbox: os and pathlib are NOT exposed at all; open, tempfile,
      base64, urllib are restricted wrappers
    """

    # Handler list names on bpy.app.handlers to snapshot/restore
    _HANDLER_NAMES = (
        "depsgraph_update_post",
        "depsgraph_update_pre",
        "frame_change_post",
        "frame_change_pre",
        "load_factory_preferences_post",
        "load_factory_startup_post",
        "load_post",
        "load_pre",
        "object_bake_cancel",
        "object_bake_complete",
        "object_bake_pre",
        "redo_post",
        "redo_pre",
        "render_cancel",
        "render_complete",
        "render_init",
        "render_post",
        "render_pre",
        "render_stats",
        "render_write",
        "save_post",
        "save_pre",
        "undo_post",
        "undo_pre",
        "version_update",
    )

    # Agent turn tracking for undo grouping
    _in_agent_turn: bool = False
    _undo_pushed_this_turn: bool = False

    def __init__(self):
        """Initialize the executor."""
        self._last_scene_state: Optional[dict] = None
        self._execution_lock = threading.Lock()

    def _snapshot_handlers(self) -> dict[str, list]:
        """Snapshot all bpy.app.handlers lists before script execution."""
        snapshot = {}
        for name in self._HANDLER_NAMES:
            handler_list = getattr(bpy.app.handlers, name, None)
            if handler_list is not None:
                snapshot[name] = list(handler_list)
        return snapshot

    def _cleanup_handlers(self, snapshot: dict[str, list]) -> None:
        """Remove any handlers that were added since the snapshot.

        Prevents scripts from installing persistent backdoors via handlers.
        """
        for name, before_list in snapshot.items():
            handler_list = getattr(bpy.app.handlers, name, None)
            if handler_list is None:
                continue
            before_set = set(id(h) for h in before_list)
            added = [h for h in handler_list if id(h) not in before_set]
            for handler in added:
                try:
                    handler_list.remove(handler)
                    logger.warning(
                        "Cleaned up handler added by script: %s.%s (%s)",
                        "bpy.app.handlers", name,
                        getattr(handler, '__name__', repr(handler)),
                    )
                except ValueError:
                    pass

    def begin_agent_turn(self) -> None:
        """Signal the start of an agent turn (multi-tool sequence)."""
        if not self._in_agent_turn:
            self._in_agent_turn = True
            self._undo_pushed_this_turn = False
            logger.debug("Agent turn started")

    def end_agent_turn(self) -> None:
        """Signal the end of an agent turn."""
        if self._in_agent_turn:
            self._in_agent_turn = False
            self._undo_pushed_this_turn = False
            logger.debug("Agent turn ended")

    def execute(self, script: str, push_undo: bool = True) -> ExecutionResult:
        """
        Execute a bpy script safely.

        Args:
            script: Python script to execute
            push_undo: Whether to push an undo step before execution

        Returns:
            ExecutionResult with success status, output, and detected changes
        """
        # Guard against overlapping executions (thread-safe)
        if not self._execution_lock.acquire(blocking=False):
            logger.warning("Script execution already in progress, skipping")
            return ExecutionResult(
                success=False,
                error="Previous script still executing",
            )

        # Capture scene state before execution
        before_state = self._capture_scene_state()

        # Push undo step -- only once per agent turn when grouping is active
        if push_undo:
            should_push = True
            if self._in_agent_turn:
                if self._undo_pushed_this_turn:
                    should_push = False
                else:
                    self._undo_pushed_this_turn = True
            if should_push:
                try:
                    bpy.ops.ed.undo_push(message="Mixie Chat Script")
                except RuntimeError:
                    pass

        # Snapshot handlers before execution to detect additions
        handler_snapshot = self._snapshot_handlers()

        # Capture stdout/stderr
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        captured_stdout = StringIO()
        captured_stderr = StringIO()

        result = ExecutionResult(success=False)

        try:
            # Redirect output
            sys.stdout = captured_stdout
            sys.stderr = captured_stderr

            # Create execution namespace with bpy access and restricted builtins.
            # Security: only safe, non-dangerous modules are pre-injected.
            # NOT exposed at all: os, pathlib -- the real modules grant
            # os.system/os.environ/Path.write_text etc., a full sandbox escape.
            # filesystem access is limited to the restricted open/tempfile below.
            import math
            import re
            import random
            import runpy
            import colorsys
            import datetime
            import collections
            import bmesh
            import mathutils
            import bpy_extras
            import imbuf
            import numpy

            exec_namespace = {
                "__builtins__": get_safe_builtins(),
                "bpy": bpy,
                "__name__": "__main__",
                # Safe modules (unrestricted)
                "json": json,
                "math": math,
                "random": random,
                "runpy": runpy,
                "colorsys": colorsys,
                "re": re,
                "datetime": datetime,
                "collections": collections,
                "time": time,
                "numpy": numpy,
                # Blender modules
                "bmesh": bmesh,
                "mathutils": mathutils,
                "bpy_extras": bpy_extras,
                "imbuf": imbuf,
                # Restricted modules -- only safe subsets exposed
                # (see sandbox_modules.py for implementation)
                "base64": RESTRICTED_BASE64,
                "tempfile": RESTRICTED_TEMPFILE,
                "urllib": RESTRICTED_URLLIB,
                "open": restricted_open,
            }

            # Restricted __import__: allows "import bpy", "import json" etc.
            # (which are already in exec_namespace) but blocks arbitrary imports.
            # Addon modules (mixar.*) are allowed through to the real __import__
            # so pre-written tool scripts can access paint/addon internals.
            _allowed = set(exec_namespace.keys()) - {"__builtins__", "__name__", "open"}
            _real_import = builtins.__import__
            def _restricted_import(name, *args, **kwargs):
                if name in _allowed:
                    return exec_namespace[name]
                # Allow addon's own modules (e.g. mixar.modules.paint.*) and numpy's
                # internal submodules (numpy lazily imports numpy.core._methods etc.).
                # NOT urllib.* — only the RestrictedUrllib wrapper may reach the network.
                top_module = name.split(".")[0]
                if top_module in ("mixar", "numpy"):
                    return _real_import(name, *args, **kwargs)
                raise ImportError(
                    f"Module '{name}' is not available. "
                    f"Allowed modules: {', '.join(sorted(_allowed))}"
                )
            exec_namespace["__builtins__"]["__import__"] = _restricted_import

            # AST validation: block sandbox escape patterns before compilation
            ast_error = validate_script_ast(script)
            if ast_error:
                raise SandboxViolationError(ast_error)

            # Crash-safety transform: rewrite `for x in <coll>.all_objects:` into
            # `for x in list(...):` so a mutation inside the loop can't free the
            # live RNA array the C iterator walks (a native segfault we cannot
            # catch). The transformed AST is compiled directly (no unparse round
            # trip). See sandbox_transform.py for the full rationale.
            tree = ast.parse(script, filename="<agent_script>", mode="exec")
            tree = snapshot_collection_iterations(tree)

            # Execute the script in the sandboxed namespace
            compiled = compile(tree, "<agent_script>", "exec")  # noqa: S102
            exec_start = time.time()
            exec(compiled, exec_namespace)  # noqa: S102
            elapsed = time.time() - exec_start

            if elapsed > SCRIPT_TIMEOUT_THRESHOLD:
                logger.warning(
                    "Script execution took %.1fs (threshold: %.0fs)",
                    elapsed, SCRIPT_TIMEOUT_THRESHOLD,
                )

            # Check for return value using __RESULT__ convention
            if "__RESULT__" in exec_namespace:
                result.return_value = exec_namespace["__RESULT__"]

            result.success = True

            # NOTE: Do NOT call view_layer.update() here!
            # UV operations toggle edit mode, which deallocates vertex/edge/BVH structures.
            # An immediate update() forces depsgraph evaluation while memory is still being
            # deallocated, causing segfaults. Blender's rendering pipeline handles this.

        except Exception as e:
            result.success = False
            result.error = str(e)
            result.traceback = traceback.format_exc()
            # Log the full stack: str(e) alone (e.g. a bare KeyError) is often
            # uninformative, and to_dict() forwards the traceback to the caller so
            # backend logs can name the failing line instead of a "Type: message".
            logger.error("Script execution failed: %s\n%s", e, result.traceback)

        finally:
            self._execution_lock.release()

            # Clean up any handlers the script may have installed
            self._cleanup_handlers(handler_snapshot)

            # Restore stdout/stderr
            sys.stdout = old_stdout
            sys.stderr = old_stderr

            # Capture output
            result.output = captured_stdout.getvalue()
            stderr_output = captured_stderr.getvalue()
            if stderr_output:
                result.output += f"\nStderr:\n{stderr_output}"

        # Capture scene state after execution and detect changes
        after_state = self._capture_scene_state()
        changes = self._detect_changes(before_state, after_state)

        result.created_objects = changes["created"]
        result.modified_objects = changes["modified"]
        result.deleted_objects = changes["deleted"]

        return result

    def _capture_scene_state(self) -> dict:
        """Capture current scene state for change detection."""
        state = {
            "objects": {},
            "materials": set(),
        }

        try:
            for obj in bpy.data.objects:
                state["objects"][obj.name] = {
                    "type": obj.type,
                    "location": tuple(obj.location),
                    "rotation": tuple(obj.rotation_euler),
                    "scale": tuple(obj.scale),
                    "material_count": (
                        len(obj.material_slots) if hasattr(obj, "material_slots") else 0
                    ),
                }
            state["materials"] = set(mat.name for mat in bpy.data.materials)

        except (AttributeError, RuntimeError) as e:
            logger.debug(f"Warning: Could not capture scene state: {e}")

        return state

    def _detect_changes(self, before: dict, after: dict) -> dict:
        """Detect what changed between two scene states."""
        before_objects = set(before.get("objects", {}).keys())
        after_objects = set(after.get("objects", {}).keys())

        created = list(after_objects - before_objects)
        deleted = list(before_objects - after_objects)

        modified = []
        for obj_name in before_objects & after_objects:
            before_props = before["objects"].get(obj_name, {})
            after_props = after["objects"].get(obj_name, {})
            if before_props != after_props:
                modified.append(obj_name)

        return {
            "created": created,
            "modified": modified,
            "deleted": deleted,
        }


# Global executor instance
_executor: Optional[ScriptExecutor] = None


def get_executor() -> ScriptExecutor:
    """Get the global ScriptExecutor instance."""
    global _executor
    if _executor is None:
        _executor = ScriptExecutor()
    return _executor
