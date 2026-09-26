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
from io import StringIO
from typing import Optional

import bpy

from ..constants import (
    AGENT_UNDO_GROUP_PER_TURN,
    AGENT_UNDO_MAX_CHECKPOINTS_PER_TURN,
    SCRIPT_TIMEOUT_THRESHOLD,
)

logger = get_logger(__name__)


class SandboxViolationError(RuntimeError):
    """Raised when a script fails AST sandbox validation."""
    pass


# Restricted module wrappers (see sandbox_modules.py for implementation)
from .sandbox_modules import (
    safe_module,
    RESTRICTED_BASE64,
    RESTRICTED_STRING,
    RESTRICTED_TEMPFILE,
    RESTRICTED_URLLIB,
    restricted_open,
)
from .sandbox_builtins import get_safe_builtins
from .executor_handlers import HandlerCleanupMixin
from .executor_result import ExecutionResult  # noqa: F401 — re-exported
from .sandbox_validator import validate_script_ast
from .sandbox_transform import snapshot_collection_iterations
from .executor_scene_state import SceneStateMixin


class ScriptExecutor(SceneStateMixin, HandlerCleanupMixin):
    """
    Safely executes generated bpy scripts.

    Features:
    - Captures stdout/stderr
    - Detects scene changes (created/modified/deleted objects)
    - Handles errors gracefully
    - Integrates with Blender's undo system
    - Cleans up bpy.app.handlers installed by scripts (HandlerCleanupMixin,
      which exempts the preview-render callbacks by identity)
    - Scene snapshot / diff and Object-mode restore (SceneStateMixin)
    - Hardened sandbox: os and pathlib are NOT exposed at all; open, tempfile,
      base64, urllib are restricted wrappers
    """

    # Agent turn tracking for undo checkpoints (see AGENT_UNDO_* constants)
    # One entry per chat session (parallel scenes): session id -> [successful
    # pushes this turn, failure already logged]. Blender's undo stack itself
    # is document-wide; only the per-turn caps are per session.
    _turns: dict = {}
    #: the session whose script is executing (set by ``execute``)
    _current_session: str = ""

    def __init__(self):
        """Initialize the executor."""
        self._last_scene_state: Optional[dict] = None
        self._execution_lock = threading.Lock()

    @property
    def _in_agent_turn(self) -> bool:
        return self._current_session in self._turns

    def _turn(self) -> Optional[list]:
        return self._turns.get(self._current_session)

    def begin_agent_turn(self, session_id: str = "") -> None:
        """Signal the start of an agent turn (multi-tool sequence).

        Idempotent: the queue processor calls it for every streamed event,
        so the turn begins with the first one and the per-turn undo counters
        reset exactly once per turn.
        """
        if session_id not in self._turns:
            self._turns[session_id] = [0, False]
            logger.debug("Agent turn started (%s)", session_id[:8])

    def end_agent_turn(self, session_id: Optional[str] = None) -> None:
        """Signal the end of an agent turn. ``None`` ends every session's."""
        if session_id is None:
            if self._turns:
                self._turns.clear()
                logger.debug("Agent turns ended (all)")
            return
        if self._turns.pop(session_id, None) is not None:
            logger.debug("Agent turn ended (%s)", session_id[:8])

    def _should_push_undo(self, grouping: bool = None) -> bool:
        """Whether THIS script should push an undo checkpoint.

        Outside a turn every script pushes. Inside a turn, grouped mode
        (AGENT_UNDO_GROUP_PER_TURN, or the per-call override) pushes once —
        the pre-turn state, so one Ctrl-Z reverts the whole multi-tool turn
        — and per-script mode (default) pushes before each script until
        AGENT_UNDO_MAX_CHECKPOINTS_PER_TURN checkpoints exist, so the user
        can step back through the agent's work one tool at a time without
        a long turn evicting the pre-turn state from Blender's undo stack.
        Only SUCCESSFUL pushes are counted, so a failed push is retried by
        the next script instead of silently leaving the turn without one.
        """
        group_per_turn = (
            AGENT_UNDO_GROUP_PER_TURN if grouping is None else grouping
        )
        turn = self._turn()
        if turn is None:
            return True
        limit = 1 if group_per_turn else AGENT_UNDO_MAX_CHECKPOINTS_PER_TURN
        return turn[0] < limit

    def _push_undo_checkpoint(self) -> bool:
        """Push an undo checkpoint; retry once inside an explicit window
        context (undo_push's poll fails when the script runs without one).
        Returns True only when a checkpoint was actually created."""
        try:
            bpy.ops.ed.undo_push(message="Mixie Chat Script")
            return True
        except RuntimeError:
            pass
        try:
            windows = bpy.context.window_manager.windows
            if not windows:
                return False
            with bpy.context.temp_override(window=windows[0]):
                bpy.ops.ed.undo_push(message="Mixie Chat Script")
            return True
        except (RuntimeError, AttributeError):
            return False

    def _push_undo_for_script(self) -> bool:
        """Push this script's checkpoint and account for it.

        A success counts towards the turn's cap. A failure never aborts the
        script: it is NOT counted (so the next script retries instead of the
        turn silently having no checkpoint) and it is logged — once per turn,
        because a context that cannot push will fail for every script in it.
        """
        turn = self._turn()
        if self._push_undo_checkpoint():
            if turn is not None:
                turn[0] += 1
            return True
        if turn is None or not turn[1]:
            logger.warning(
                "Undo checkpoint failed - this script's changes may not be "
                "individually undoable"
            )
            if turn is not None:
                turn[1] = True
        return False

    def execute(self, script: str, push_undo: bool = True, session_id: str = "") -> ExecutionResult:
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

        self._current_session = session_id or ""
        # Capture scene state before execution
        before_state = self._capture_scene_state()
        mode_before = self._interaction_mode()

        # Push undo step BEFORE the script runs, so the first push of a turn
        # captures the pre-turn scene. Granularity (per script up to the
        # per-turn cap, or one per turn when grouped) is decided by
        # _should_push_undo; a failed push never aborts the script — it is
        # logged once per turn and retried by the next script, where it used
        # to be silently swallowed (turns got NO checkpoint at all).
        if push_undo and self._should_push_undo():
            self._push_undo_for_script()

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
            import colorsys
            import datetime
            import collections
            import hashlib
            # Pure-Python stdlib helpers: no process, file or network access,
            # and no API that resolves an attribute from a caller-supplied name
            # (that would walk past the wrapped getattr). Deliberately NOT here:
            #   operator -- attrgetter/methodcaller take the name as a string
            #   runpy    -- run_module("os") returns the real os namespace
            #   string   -- proxied below; Formatter().get_field() is the same
            #               attrgetter hole and returns the object, not a repr
            import itertools
            import functools
            import statistics
            import heapq
            import bisect
            import copy
            import textwrap
            import fractions
            import decimal
            import bmesh
            import mathutils
            import bpy_extras
            import imbuf
            import numpy
            import struct

            exec_namespace = {
                "__builtins__": get_safe_builtins(),
                # bpy is wrapped too. It IS the capability the agent is given,
                # so every same-package child stays reachable -- bpy.ops,
                # bpy.data, bpy.types, bpy.props, bpy.app, bpy.path, bpy.utils
                # all resolve exactly as before. What the wrap refuses is the
                # foreign modules bound INSIDE it: Blender's own
                # bpy/utils/__init__.py does `import os as _os` / `import sys
                # as _sys`, so bpy.utils._os was the real os module and
                # bpy.utils._sys.modules['builtins'].exec arbitrary code --
                # reachable with no dunder, so the AST guard never saw it, and
                # through the one module every script already has. Leaving bpy
                # exempt meant this whole class of escape was still open.
                "bpy": safe_module(bpy),
                "__name__": "__main__",
                # Safe modules. Each is wrapped so it cannot hand out a
                # module from another package: `random._os`, `fractions.sys`,
                # `statistics.sys`, `datetime.sys`, `collections._sys`,
                # `re.enum.sys` and `json.codecs` were all plain attributes
                # reaching the real `os`/`builtins` without touching a single
                # dunder, so the AST guard never saw them. Same-package
                # submodules (`collections.abc`, `numpy.linalg`) still work.
                "json": safe_module(json),
                "math": safe_module(math),
                "random": safe_module(random),
                "colorsys": safe_module(colorsys),
                "re": safe_module(re),
                "datetime": safe_module(datetime),
                "collections": safe_module(collections),
                "hashlib": safe_module(hashlib),
                "time": safe_module(time),
                "numpy": safe_module(numpy),
                "struct": safe_module(struct),
                "itertools": safe_module(itertools),
                "functools": safe_module(functools),
                "statistics": safe_module(statistics),
                "heapq": safe_module(heapq),
                "bisect": safe_module(bisect),
                "copy": safe_module(copy),
                "textwrap": safe_module(textwrap),
                "fractions": safe_module(fractions),
                "decimal": safe_module(decimal),
                # Blender modules
                "bmesh": safe_module(bmesh),
                "mathutils": safe_module(mathutils),
                "bpy_extras": safe_module(bpy_extras),
                "imbuf": safe_module(imbuf),
                # Restricted modules -- only safe subsets exposed
                # (see sandbox_modules.py for implementation)
                "base64": RESTRICTED_BASE64,
                "string": RESTRICTED_STRING,
                "tempfile": RESTRICTED_TEMPFILE,
                "urllib": RESTRICTED_URLLIB,
                "open": restricted_open,
            }

            # Some first-party scene transaction scripts use
            # ``globals().get(<sentinel>)`` to gate a commit body. Exposing the
            # real globals builtin would also expose the mutable builtins map
            # and the restricted-open capability, so provide only a detached,
            # filtered snapshot of names already visible to the script.
            def _safe_globals():
                return {
                    name: value
                    for name, value in exec_namespace.items()
                    if name not in {"__builtins__", "open"}
                }

            exec_namespace["__builtins__"]["globals"] = _safe_globals

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
                # mathutils/bmesh/bpy_extras submodules (mathutils.bvhtree, bmesh.ops,
                # bpy_extras.view3d_utils, ...) grant nothing beyond the already
                # injected parents — they are reachable as attributes anyway; only
                # the `import x.y` statement form was being rejected.
                # NOT urllib.* — only the RestrictedUrllib wrapper may reach the network.
                top_module = name.split(".")[0]
                if top_module in ("mixar", "numpy", "mathutils", "bmesh", "bpy_extras"):
                    real = _real_import(name, *args, **kwargs)
                    # `import a.b` binds `a`, so handing back the real package
                    # here would return the UNWRAPPED module and undo the
                    # cross-package guard. Return the proxy we already built
                    # where there is one, and wrap first-party packages so a
                    # module that does `import os` cannot re-export it.
                    #
                    # ONLY for the no-fromlist form. With a fromlist,
                    # `__import__` returns the LEAF module and the interpreter
                    # then getattrs the names off it, so substituting the top
                    # package here broke every `from numpy.linalg import norm`
                    # / `from mathutils.geometry import ...` with "cannot
                    # import name". The leaf's own proxy is equally guarded.
                    fromlist = args[2] if len(args) > 2 else kwargs.get("fromlist")
                    if not fromlist and top_module in exec_namespace:
                        return exec_namespace[top_module]
                    return safe_module(real)
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
            # Mode hygiene: a script that left Edit/Sculpt/... mode open would
            # leave the window in it for the next script — another tab's, once
            # tabs interleave — and for the user. Restore before the routing
            # pin is lifted, while the window still shows the script's scene.
            self._restore_object_mode(mode_before)
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


# Global executor instance
_executor: Optional[ScriptExecutor] = None


def get_executor() -> ScriptExecutor:
    """Get the global ScriptExecutor instance."""
    global _executor
    if _executor is None:
        _executor = ScriptExecutor()
    return _executor
