# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Execute generated bpy scripts, capture output and detect scene changes."""

from mixar.config.logging_config import get_logger
import ast
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
    AGENT_UNDO_NEUTRAL_TOOLS,
    is_lane_scene,
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
from .sandbox_bpy import make_sandboxed_bpy
from .sandbox_import import make_restricted_import
from .sandbox_builtins import get_safe_builtins
from .executor_handlers import HandlerCleanupMixin
from .executor_result import ExecutionResult  # noqa: F401 — re-exported
from .sandbox_validator import validate_script_ast
from .sandbox_transform import snapshot_collection_iterations
from .sandbox_mesh import guard_from_mesh, guard_mesh_conversions
from .executor_scene_state import SceneStateMixin


class ScriptExecutor(SceneStateMixin, HandlerCleanupMixin):
    """
    Safely executes generated bpy scripts.

    Captures output, object changes and undo; restricts modules/builtins and
    removes untrusted handlers. Preview callbacks are exempted by identity.
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
            # [checkpoints pushed, push failure logged, scripts ran]
            self._turns[session_id] = [0, False, False]
            logger.debug("Agent turn started (%s)", session_id[:8])

    def end_agent_turn(
        self, session_id: Optional[str] = None, *, checkpoint: bool = False
    ) -> None:
        """Signal the end of an agent turn. ``None`` ends every session's.

        With ``checkpoint=True`` a turn that ran effectful scripts closes with
        one more checkpoint: the state the agent left, so undo reverts the
        turn and redo reapplies it. Only the normal ends pass it (stream
        complete / error, replay-unavailable, user Abort). Tab close, file
        load and the undo/redo handlers end turns WITHOUT a step: a push there
        records a closing tab as still working, or truncates the redo stack
        from inside the undo handler. The end-all (``None``) form never pushes.
        """
        if session_id is None:
            if self._turns:
                self._turns.clear()
                logger.debug("Agent turns ended (all)")
            return
        turn = self._turns.pop(session_id, None)
        if turn is not None:
            logger.debug("Agent turn ended (%s)", session_id[:8])
            if checkpoint and turn[2]:
                self._close_turn_checkpoint(session_id)

    def _lane_pin_blocks_push(self, session_id: str = "") -> bool:
        """Whether a window on a worker lane must stop a checkpoint.

        The skip exists for the classic undo: a memfile step written while a
        window shows a lane records the lane as the current scene, and an undo
        landing on it put the user inside the lane. Per-tab undo never moves the
        window and tags the step through ``mixar_undo_push(scene=)``, so there
        the skip only lost checkpoints: a user watching a worker through its
        card's eye when a turn ended left that turn without its closing step,
        and an undo then went past the turn's work with no redo to bring it back
        (review 2026-10-01, R6). A lane alive in the step is never restored by a
        tab's walk (the C side's lane owner class)."""
        if not self._window_on_lane_scene():
            return False
        try:
            wm = bpy.context.window_manager
            per_tab = bool(getattr(wm, "mixar_per_tab_undo", False)) and \
                callable(getattr(wm, "mixar_undo_push", None))
        except Exception:  # noqa: BLE001
            per_tab = False
        if per_tab and self._session_scene(session_id or self._current_session) is not None:
            return False
        return True

    def _close_turn_checkpoint(self, session_id: str = "") -> None:
        if self._lane_pin_blocks_push(session_id):
            logger.debug("Closing undo checkpoint skipped: window pinned to a lane scene")
            return
        if not self._push_undo_checkpoint("Mixie Chat Turn", session_id=session_id):
            logger.warning("Closing undo checkpoint failed - the turn's work may not be redoable")

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

    @staticmethod
    def _window_on_lane_scene() -> bool:
        """True while any window shows a worker lane scene (the routing pin
        of a workspace script). Fail-open: no windows, no lane."""
        try:
            for window in bpy.context.window_manager.windows:
                if is_lane_scene(getattr(window, "scene", None)):
                    return True
        except Exception:  # noqa: BLE001 — never block a script over a probe
            return False
        return False

    @staticmethod
    def _session_scene(session_id: str):
        """The scene tab a chat session belongs to, or None."""
        if not session_id:
            return None
        try:
            for scene in bpy.data.scenes:
                if getattr(scene, "mixie_session_id", "") == session_id:
                    return scene
        except Exception:  # noqa: BLE001 — bpy.data mid-teardown
            return None
        return None

    def _push_undo_checkpoint(self, message: str = "Mixie Chat Script", session_id: str = "") -> bool:
        """Push an undo checkpoint on behalf of the session's tab.

        Per-tab undo (M1) tags every step with a tab. The executor's pushes land
        from timers while the window shows whatever the user looks at, and a
        Python `scene=` override is dropped once a window is overridden, so the
        tab is passed explicitly through `WindowManager.mixar_undo_push` (a
        one-shot C-side override around ED_undo_push; needs no window). Builds
        without it fall back to `ed.undo_push`, retried inside a borrowed window
        because that operator polls for one. Returns True only when a
        checkpoint was created."""
        scene = self._session_scene(session_id or self._current_session)
        wm = bpy.context.window_manager
        pusher = getattr(wm, "mixar_undo_push", None)
        if scene is not None and callable(pusher):
            try:
                return bool(pusher(message, scene=scene))   # RNA: optional pointer = keyword-only
            except (RuntimeError, TypeError, AttributeError):
                logger.debug("mixar_undo_push failed; falling back to ed.undo_push", exc_info=True)
        try:
            bpy.ops.ed.undo_push(message=message)
            return True
        except RuntimeError:
            pass
        try:
            windows = wm.windows
            if not windows:
                return False
            with bpy.context.temp_override(window=windows[0]):
                bpy.ops.ed.undo_push(message=message)
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

    def execute(
        self, script: str, push_undo: bool = True, session_id: str = "",
        tool_name: str = "",
    ) -> ExecutionResult:
        """Execute under one lock, including preparation, snapshots and cleanup.

        ``tool_name`` is the backend tool that sent the script. Read-only tools
        (AGENT_UNDO_NEUTRAL_TOOLS) push no checkpoint and do not mark the turn
        as having run, so a chat-only turn leaves no no-op undo steps behind.
        """
        from mixar.modules.common.ui_control.core.ownership import active as ui_active
        if ui_active():
            return ExecutionResult(success=False, error="ui_busy: release native UI control before running scripts")
        # Guard against overlapping executions (thread-safe)
        if not self._execution_lock.acquire(blocking=False):
            logger.warning("Script execution already in progress, skipping")
            return ExecutionResult(
                success=False,
                error="Previous script still executing",
            )
        try:
            return self._execute_locked(script, push_undo, session_id, tool_name)
        finally:
            self._execution_lock.release()

    def _execute_locked(self, script, push_undo, session_id, tool_name=""):
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
        undo_neutral = tool_name in AGENT_UNDO_NEUTRAL_TOOLS
        turn_record = self._turn()
        if turn_record is not None and push_undo and not undo_neutral:
            turn_record[2] = True
        if push_undo and not undo_neutral and self._should_push_undo():
            if self._lane_pin_blocks_push():
                # The routing pin has the window on a worker lane: a memfile
                # step written now records the lane as the CURRENT scene, so an
                # undo landing on it would put the user inside the lane. Skip,
                # uncounted: the next MAIN-pinned script pushes the checkpoint.
                logger.debug("Undo checkpoint skipped: window pinned to a lane scene")
            else:
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
                # On top, bpy.ops / bpy.app.driver_namespace are guarded views
                # refusing the code-execution routes (sandbox_bpy.py).
                "bpy": make_sandboxed_bpy(safe_module(bpy)),
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

            # Restricted __import__: resolves pre-injected names, admits a few
            # packages, refuses the rest and every denied module (sandbox_import.py).
            exec_namespace["__builtins__"]["__import__"] = make_restricted_import(
                exec_namespace
            )

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
            tree = guard_mesh_conversions(tree)
            exec_namespace["_mixar_guard_from_mesh"] = guard_from_mesh

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
            # Mode hygiene happens at the END of the turn (`restore_turn_mode`,
            # from `finalize_turn`), never between scripts: a script may leave
            # the tab in Edit / Sculpt / Texture Paint mode on purpose for the
            # next one. Here only the mode the turn started in is noted.
            try:
                self.note_turn_mode(session_id, mode_before)
                self._cleanup_handlers(handler_snapshot)
            finally:
                # Even a cleanup/RNA failure cannot leave the app's output
                # redirected or the outer execution lock permanently held.
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
