# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Two background pumps behind the island, and what stops each of them.

The hover pump (``agent_bubble/ui/operators/hover_ops.py``) is a persistent
0.1s timer whose docstring claimed the tick was "a no-op when no bubble/pill
window exists — the operator poll fails". ``MIXAR_OT_bubble_hover_tick`` set no
``ot->poll`` at all, so ``op.poll()`` was always True and a full ``bpy.ops``
invocation ran ten times a second for the whole session. On Linux, where the
``Mixar_Window*`` GHOST helpers do not exist and the exec body is a bare
``OPERATOR_CANCELLED``, that is ten calls a second that can never do anything.

The generations pane's library reload is the other one: it is edge-triggered off
``wm.mixar_generations_revision``, and consuming an edge the gather did not act
on lost the reload entirely.
"""

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

CPP = ROOT / "src/source/blender/editors/space_agent_bubble"
BUBBLE_CC = (CPP / "space_agent_bubble.cc").read_text(encoding="utf-8")
GEN_DATA_CC = (CPP / "agent_ui_generations_data.cc").read_text(encoding="utf-8")
HOVER_PY = (
    SCRIPTS / "mixar/modules/agent_bubble/ui/operators/hover_ops.py"
).read_text(encoding="utf-8")


def _function_body(source: str, signature_start: str) -> str:
    start = source.index(signature_start)
    open_brace = source.index("{", start)
    depth = 0
    for i in range(open_brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
    raise AssertionError(f"unterminated function: {signature_start}")


# -------------------------------------------------------------------------- #
# Hover pump
# -------------------------------------------------------------------------- #


def test_hover_tick_operator_has_a_real_poll():
    body = _function_body(BUBBLE_CC, "void MIXAR_OT_bubble_hover_tick(")
    assert "ot->poll = mixar_bubble_hover_tick_poll;" in body, (
        "without a poll callback the Python pump's op.poll() is always True"
    )


def test_hover_tick_poll_is_false_without_a_window_and_off_the_allowlist():
    """No bubble and no pill means nothing to hit-test; a platform with no
    ``Mixar_Window*`` helpers means nothing the exec could ever do."""
    body = _function_body(BUBBLE_CC, "static bool mixar_bubble_hover_tick_poll(")
    assert "g_bubble_ghostwin != nullptr || g_pill_ghostwin != nullptr" in body
    assert "#if defined(__APPLE__) || defined(_WIN32)" in body
    assert "#else\n  return false;" in body, (
        "the platform branch must refuse, not fall through to the window check"
    )


def test_hover_pump_registration_is_gated_on_the_platform_allowlist():
    """`BUBBLE_WINDOW_CONTROLS_SUPPORTED` is the allowlist the rest of the
    bubble's window controls already gate on; the timer must use the same one
    rather than an inline `sys.platform` test of its own."""
    assert "BUBBLE_WINDOW_CONTROLS_SUPPORTED" in HOVER_PY
    register = HOVER_PY[HOVER_PY.index("def register():") :]
    register = register[: register.index("def unregister():")]
    assert "if not BUBBLE_WINDOW_CONTROLS_SUPPORTED:" in register
    assert register.index("if not BUBBLE_WINDOW_CONTROLS_SUPPORTED:") < register.index(
        "bpy.app.timers.register("
    ), "the gate must precede the timer registration"


def test_hover_tick_failures_are_reported_once_rather_than_swallowed():
    """A bare `except Exception: pass` hid genuine failures in the collapse
    logic forever. A failing tick fails every tick, so it is reported once and
    then suppressed — 10 tracebacks a second is an outage, not a log."""
    assert "except Exception:\n        pass" not in HOVER_PY
    tick = HOVER_PY[HOVER_PY.index("def _hover_tick():") : HOVER_PY.index("def register():")]
    assert "_logger.exception(" in tick
    assert "_reported_failure" in tick
    assert "return _TICK_SECONDS" in tick, "a failed tick must not kill the pump"


def test_hover_pump_imports_constants_rather_than_restating_them():
    """`constants.py` owns the allowlist; this module is a consumer of it."""
    assert re.search(
        r"^from mixar\.modules\.agent_bubble\.constants import "
        r"BUBBLE_WINDOW_CONTROLS_SUPPORTED$",
        HOVER_PY,
        re.M,
    )
    assert 'sys.platform in {' not in HOVER_PY


def test_hover_pump_register_is_a_no_op_off_the_allowlist():
    """Behavioural check against the mocked bpy: unsupported platform, no
    timer; supported platform, one timer."""
    sys.modules.setdefault("bpy.utils.previews", MagicMock(name="bpy.utils.previews"))
    from mixar.modules.testing.mock_bpy import install_bpy_mock

    install_bpy_mock()

    import importlib.util

    import bpy

    spec = importlib.util.spec_from_file_location(
        "_island_chrome_hover_ops",
        SCRIPTS / "mixar/modules/agent_bubble/ui/operators/hover_ops.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    registered: list = []
    bpy.app.timers.is_registered = lambda fn: fn in registered
    bpy.app.timers.register = lambda fn, **kwargs: registered.append(fn)
    bpy.app.timers.unregister = lambda fn: registered.remove(fn)

    module.BUBBLE_WINDOW_CONTROLS_SUPPORTED = False
    module.register()
    assert registered == [], "the pump must not start where it can do nothing"

    module.BUBBLE_WINDOW_CONTROLS_SUPPORTED = True
    module.register()
    assert registered == [module._hover_tick]
    module.register()
    assert len(registered) == 1, "register() must stay idempotent"
    module.unregister()
    assert registered == []


# -------------------------------------------------------------------------- #
# Generations revision edge
# -------------------------------------------------------------------------- #


def test_generations_reload_edge_is_not_consumed_by_a_gather_that_ignores_it():
    """`gather_assets` clears only the library matching `only_name`.

    On the Asset Library source browsing some OTHER library, the old code still
    advanced `g_seen_revision`, so "Mixar Generations" was never cleared and the
    freshly archived tile stayed missing until the NEXT archive bumped the
    revision again.
    """
    body = _function_body(GEN_DATA_CC, "void agent_ui_generations_gather(")
    assert "covers_generations" in body
    guard = re.search(
        r"reload = revision != g_seen_revision && covers_generations;\s*"
        r"if \(reload\) \{\s*g_seen_revision = revision;",
        body,
    )
    assert guard is not None, (
        "the edge must be consumed only where the generations library is "
        "actually re-read"
    )
    assert "reload = revision != g_seen_revision;" not in body


def test_generations_reload_covers_the_all_libraries_case():
    """An empty library name means "every registered library", which includes
    the generations one — that gather does act on the edge."""
    body = _function_body(GEN_DATA_CC, "void agent_ui_generations_gather(")
    covers = body[body.index("const bool covers_generations") :]
    covers = covers[: covers.index(";")]
    assert "r_data->source != GEN_SOURCE_LIBRARY" in covers
    assert "r_data->library[0] == '\\0'" in covers
    assert "STREQ(r_data->library, GENERATIONS_LIBRARY_NAME)" in covers


def test_generations_seen_revision_survives_a_file_load_by_inequality():
    """`wm.mixar_generations_revision` lives on the WindowManager and restarts
    at 0 on every file load, while `g_seen_revision` is a process global. An
    inequality reads that reset as one reload — which a new file wants anyway;
    a `>` comparison would strand the pane on the previous file's read."""
    body = _function_body(GEN_DATA_CC, "void agent_ui_generations_gather(")
    assert "revision > g_seen_revision" not in body
    assert "revision != g_seen_revision" in body
