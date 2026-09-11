# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pane message storage, dispatch and generation feedback contracts."""
import ast
import re
from pathlib import Path
from types import SimpleNamespace

from pane_feedback_contract import (
    CPP,
    PY,
    FEEDBACK,
    CMAKE,
    CHANNEL_PY,
    CHANNEL_SRC,
    DISPATCH_SRC,
    CHANNEL_PROPS,
    CHANNEL,
)

# -------------------------------------------------------------------------
# C. The pane-message channel itself


def _register_assignments():
    """``{property name: the Call that defines it}`` inside ``register()``."""
    tree = ast.parse(CHANNEL_SRC)
    fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "register"
    )
    out = {}
    for stmt in ast.walk(fn):
        if not isinstance(stmt, ast.Assign) or not isinstance(stmt.value, ast.Call):
            continue
        target = stmt.targets[0]
        if isinstance(target, ast.Attribute):
            out[target.attr] = stmt.value
    return out


def test_the_channel_is_three_windowmanager_properties():
    """WindowManager, never Scene.

    Which message a pane is showing is per-session UI state: it must not be
    serialized into a shared ``.blend`` and must not participate in undo.
    """
    assigned = _register_assignments()
    assert set(assigned) == set(CHANNEL_PROPS), sorted(assigned)
    assert tuple(CHANNEL.PROP_NAMES) == CHANNEL_PROPS, CHANNEL.PROP_NAMES

    # The properties hang off ``bpy.types.WindowManager`` (bound to a local).
    assert re.search(r"wm\s*=\s*bpy\.types\.WindowManager", CHANNEL_SRC), (
        "the channel does not register on WindowManager"
    )
    assert "bpy.types.Scene" not in CHANNEL_SRC, (
        "a pane message must never be serialized into a shared .blend"
    )


def test_every_channel_property_is_skip_save():
    assigned = _register_assignments()
    for name, call in assigned.items():
        options = next(
            (kw.value for kw in call.keywords if kw.arg == "options"), None
        )
        assert options is not None, f"{name} declares no options"
        assert "SKIP_SAVE" in ast.unparse(options), (
            f"{name} is not SKIP_SAVE, so it would be saved into the .blend"
        )


def test_the_channel_property_types_match_what_the_painter_reads():
    """String message, integer level, integer serial.

    The C++ side reads them through ``kit_read_string`` / ``kit_read_int``,
    which type-check the property and silently fall back when it disagrees.
    """
    assigned = _register_assignments()
    expected = {
        "mixar_pane_message": "StringProperty",
        "mixar_pane_message_level": "IntProperty",
        "mixar_pane_message_serial": "IntProperty",
    }
    for name, factory in expected.items():
        assert assigned[name].func.id == factory, (
            f"{name} is a {assigned[name].func.id}, not a {factory}"
        )


def test_the_level_constants_agree_across_the_two_languages():
    """0 none, 1 info, 2 warning, 3 error — deliberately NOT eReportType bits.

    The C++ painter reads the raw integer, so a value drifting on either side
    is silent: the line simply paints in the wrong colour, or not at all.
    """
    python = {
        match.group(1): int(match.group(2))
        for match in re.finditer(r"^(LEVEL_\w+) = (\d+)$", CHANNEL_SRC, re.M)
    }
    cpp = {
        match.group(1): int(match.group(2))
        for match in re.finditer(r"PANE_MSG_(LEVEL_\w+) = (\d+),", FEEDBACK)
    }
    assert python == {
        "LEVEL_NONE": 0,
        "LEVEL_INFO": 1,
        "LEVEL_WARNING": 2,
        "LEVEL_ERROR": 3,
    }, python
    assert cpp == python, f"C++ {cpp} disagrees with Python {python}"


def test_the_channel_has_exactly_one_writer():
    """One definition, so text / level / serial can never drift apart.

    Three scattered assignments would let a caller leave the level describing
    a previous message, or forget the serial and have the painter treat a new
    refusal as "still showing".
    """
    definitions = [
        path.name
        for path in PY.rglob("*.py")
        if re.search(r"^def set_pane_message\(", path.read_text(encoding="utf-8"), re.M)
    ]
    assert definitions == ["pane_message_props.py"], definitions

    for path in PY.rglob("*.py"):
        if path == CHANNEL_PY:
            continue
        source = path.read_text(encoding="utf-8")
        for prop in CHANNEL_PROPS:
            assert f".{prop} =" not in source, (
                f"{path.name} assigns {prop} directly instead of calling "
                f"set_pane_message()"
            )


def test_the_writer_bumps_the_serial_on_every_write_including_a_repeat():
    """A repeat is news: the user pressed Generate again and was refused again.

    Without the bump the painter reads an unchanged channel as "still
    showing", lets the TTL expire, and the second refusal is silent.
    """
    wm = SimpleNamespace(
        mixar_pane_message="",
        mixar_pane_message_level=0,
        mixar_pane_message_serial=0,
    )
    previous = CHANNEL.bpy.context.window_manager
    CHANNEL.bpy.context.window_manager = wm
    try:
        CHANNEL.set_pane_message("No image selected", CHANNEL.LEVEL_ERROR)
        assert wm.mixar_pane_message == "No image selected"
        assert wm.mixar_pane_message_level == CHANNEL.LEVEL_ERROR
        assert wm.mixar_pane_message_serial == 1

        CHANNEL.set_pane_message("No image selected", CHANNEL.LEVEL_ERROR)
        assert wm.mixar_pane_message_serial == 2, "a repeat must still be news"

        CHANNEL.clear_pane_message()
        assert wm.mixar_pane_message == ""
        assert wm.mixar_pane_message_level == CHANNEL.LEVEL_NONE
        assert wm.mixar_pane_message_serial == 3, "clearing is a write too"
    finally:
        CHANNEL.bpy.context.window_manager = previous


def test_the_writer_never_breaks_the_generation_it_reports_on():
    """No window manager, an unregistered island, a mistyped value — all fine.

    This runs on the paid-action path; a message is never worth an exception.
    """
    previous = CHANNEL.bpy.context.window_manager
    CHANNEL.bpy.context.window_manager = None
    try:
        CHANNEL.set_pane_message("anything", CHANNEL.LEVEL_INFO)
    finally:
        CHANNEL.bpy.context.window_manager = previous

    CHANNEL.bpy.context.window_manager = object()
    try:
        CHANNEL.set_pane_message("anything", CHANNEL.LEVEL_INFO)
    finally:
        CHANNEL.bpy.context.window_manager = previous


# -------------------------------------------------------------------------
# D. The one dispatcher writes it, on every outcome


def _dispatcher_execute():
    tree = ast.parse(DISPATCH_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "execute":
            return node
    raise AssertionError("the dispatcher has no execute()")


def _pane_message_calls(fn):
    return [
        node
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_pane_message"
    ]


def test_the_dispatcher_speaks_on_every_outcome():
    """Every path out of ``execute`` puts something on the pane.

    ``mixie.moodboard_prompt_generate`` is the ONE dispatcher every pane's
    Generate and Enter route through, so a path that returns silently is a
    Generate button that did nothing and said nothing.
    """
    execute = _dispatcher_execute()
    calls = _pane_message_calls(execute)
    returns = [n for n in ast.walk(execute) if isinstance(n, ast.Return)]
    assert len(calls) == len(returns), (
        f"{len(returns)} ways out of execute() but only {len(calls)} messages"
    )

    levels = [call.args[1].value for call in calls]
    assert levels.count("LEVEL_WARNING") >= 3, (
        "the unresolved-owner / missing-operator / failing-poll paths must "
        f"all warn: {levels}"
    )
    assert "LEVEL_ERROR" in levels, "the RuntimeError refusal is not an error"
    assert "LEVEL_INFO" in levels, "success says nothing"


def test_the_dispatcher_keeps_reporting_as_well():
    """The Info editor and the N-panel are still real surfaces."""
    execute = _dispatcher_execute()
    reports = [
        node
        for node in ast.walk(execute)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "report"
    ]
    assert len(reports) >= 4, (
        "self.report() was dropped; the Info editor and N-panel lose the text"
    )


def test_the_dispatcher_still_deprefixes_blenders_error_string():
    """``bpy.ops`` wraps an ``{'ERROR'}`` report as ``Error: <sentence>``.

    The pane must show the operator's own sentence, not a doubled one — and
    the de-prefixing has to happen BEFORE the message reaches the channel.
    """
    source = DISPATCH_SRC
    strip = source.index('message[len("Error: "):]')
    error_message = source.index('_pane_message(message, "LEVEL_ERROR")')
    assert strip < error_message, (
        "the pane is written before the 'Error: ' prefix is stripped"
    )


def test_the_moodboard_never_hard_depends_on_the_island():
    """The island is another module and may not be registered at all.

    A bare import would make a Generate in the N-panel fail on a build
    without the agent bubble.
    """
    helper = next(
        node
        for node in ast.walk(ast.parse(DISPATCH_SRC))
        if isinstance(node, ast.FunctionDef) and node.name == "_pane_message"
    )
    handlers = [
        h
        for node in ast.walk(helper)
        if isinstance(node, ast.Try)
        for h in node.handlers
    ]
    assert any(
        isinstance(h.type, ast.Name) and h.type.id == "ImportError"
        for h in handlers
    ), "the island import is not guarded against ImportError"

    # ...and the import is local to the helper, never module-level.
    module_imports = [
        node
        for node in ast.parse(DISPATCH_SRC).body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert not any(
        "agent_bubble" in ast.unparse(node) for node in module_imports
    ), "the moodboard imports the island at module scope"


# -------------------------------------------------------------------------
# Build wiring


def test_the_feedback_translation_unit_is_built():
    assert "agent_ui_pane_kit_feedback.cc" in CMAKE, (
        "the feedback TU is not in the space_agent_bubble CMakeLists"
    )


def test_no_owned_pane_source_crosses_the_500_line_rule():
    for name in (
        "agent_ui_pane_kit.cc",
        "agent_ui_pane_kit_feedback.cc",
        "agent_ui_pane_kit_thumbs.cc",
        "agent_ui_tab3d.cc",
        "agent_ui_tab3d_params.cc",
        "agent_ui_tabmedia.cc",
        "agent_ui_tabmedia_util.cc",
        "agent_ui_tabsplat.cc",
        "agent_ui_tabsplat_paint.cc",
    ):
        lines = len((CPP / name).read_text(encoding="utf-8").splitlines())
        assert lines <= 500, f"{name} is {lines} lines"


# ---------------------------------------------------------------------------
# A live job is information, not a lock.


def _pane(name: str) -> str:
    from pathlib import Path

    return (
        Path(__file__).resolve().parents[1]
        / "src/source/blender/editors/space_agent_bubble"
        / name
    ).read_text(encoding="utf-8")


def test_a_queued_job_does_not_disarm_generate():
    """This is a QUEUE — stacking jobs is the point. Gating Generate on "a job
    of this service is live" would stop the user submitting a second one, and
    the queue exists precisely so they can. Only a missing prompt field or an
    unusable catalog may disarm it."""
    media = _pane("agent_ui_tabmedia.cc")
    can_generate = [ln for ln in media.splitlines() if "const bool can_generate" in ln]
    assert can_generate and "busy" not in can_generate[0], can_generate

    tab3d = _pane("agent_ui_tab3d.cc")
    armed = [ln for ln in tab3d.splitlines() if "const bool armed" in ln]
    assert armed and "generating" not in armed[0], armed

    splat = _pane("agent_ui_tabsplat.cc")
    assert "state.active_jobs == 0" not in splat


def test_the_count_is_what_carries_the_feedback():
    """With the button still armed, the label is the only thing that tells the
    user their submit landed — so it must show the count, from one helper."""
    kit = _pane("agent_ui_pane_kit_feedback.cc")
    assert "void pane_queue_label(" in kit
    assert '"Queued (%d)"' in kit
    for name in ("agent_ui_tabmedia.cc", "agent_ui_tab3d.cc"):
        assert "pane_queue_label(" in _pane(name), name
