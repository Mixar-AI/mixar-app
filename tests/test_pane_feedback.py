# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Feedback contracts of the agent island's generation panes.

The island is its own always-on-top window: no status bar, no Info editor. So
the two things the moodboard N-panel leans on are both invisible here — the
per-tab ``scene.mixie_*_is_generating`` flags (which several enqueue paths
never set at all) and ``self.report()``. Pressing Generate therefore produced
NO feedback whatsoever, even when the click was refused.

The message line that fixes that reads a DEDICATED channel written only by
the panes' own Generate dispatcher, never Blender's global report list: that
list carries the whole app's activity, Mixar's own agent running sandboxed
Blender scripts included, so the pane painted unrelated bpy script output
above the user's prompt.

Mostly source-level, like the rest of the island's C++ surface (see
``test_agent_bubble_panes.py``): these are draw rules whose C++ half has no
importable Python counterpart. The channel's Python half IS importable and is
exercised directly.
"""

import ast
import re
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "src/source/blender/editors/space_agent_bubble"
PY = ROOT / "src/scripts/mixar/modules"

if str(ROOT / "src/scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "src/scripts"))

FEEDBACK = (CPP / "agent_ui_pane_kit_feedback.cc").read_text()
KIT_HH = (CPP / "agent_ui_pane_kit.hh").read_text()
QUEUE_CC = (CPP / "agent_ui_queue.cc").read_text()
CMAKE = (CPP / "CMakeLists.txt").read_text()

CHANNEL_PY = PY / "agent_bubble/ui/properties/pane_message_props.py"
DISPATCH_PY = PY / "moodboard/ui/operators/prompt_generate_ops.py"
CHANNEL_SRC = CHANNEL_PY.read_text()
DISPATCH_SRC = DISPATCH_PY.read_text()

#: The one channel, named in both languages.
CHANNEL_PROPS = (
    "mixar_pane_message",
    "mixar_pane_message_level",
    "mixar_pane_message_serial",
)

from mixar.modules.agent_bubble.ui.properties import (  # noqa: E402
    pane_message_props as CHANNEL,
)

# Every translation unit a pane's own drawing lives in. The Splat pane is
# split (state/controls vs geometry/painting), so both halves count as "the
# Splat pane" for these contracts.
PANE_SOURCES = {
    name: (CPP / name).read_text()
    for name in (
        "agent_ui_tab3d.cc",
        "agent_ui_tabmedia.cc",
        "agent_ui_tabsplat.cc",
        "agent_ui_tabsplat_paint.cc",
    )
}
PANES = {
    "3D": ("agent_ui_tab3d.cc",),
    "Media": ("agent_ui_tabmedia.cc",),
    "Splat": ("agent_ui_tabsplat.cc", "agent_ui_tabsplat_paint.cc"),
}

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"//[^\n]*")


def _code(source: str) -> str:
    """`source` with comments removed — these tests are about what RUNS.

    Every rule below is also *described* in a comment somewhere near the code
    that obeys it, so a naive substring search matches the prose that explains
    the old behaviour just as happily as the old behaviour itself.
    """
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", source))


def _pane_code(pane: str) -> str:
    return "\n".join(_code(PANE_SOURCES[name]) for name in PANES[pane])


# -------------------------------------------------------------------------
# A. Busy state comes from the unified queue, not the legacy scene flags


def test_no_pane_reads_a_legacy_is_generating_flag():
    """The flags are not written on the panes' path.

    A pane's Generate goes through ``mixie.moodboard_prompt_generate`` into
    the moodboard generate operators and on to ``enqueue_generation``. Only
    the callers that pass a ``scene_flag`` get a
    ``create_scene_flag_listener``, and the Image Gen tab operator and the
    World Labs flow pass none — so ``mixie_imagegen_is_generating`` and
    friends stayed False forever and the button never changed. The ones that
    DO pass a flag only see it flip on the queue's next change edge, i.e.
    after the submit. The queue mirror is the source of truth.
    """
    for pane in PANES:
        assert "is_generating" not in _pane_code(pane), (
            f"{pane} pane still reads a scene *_is_generating flag; the busy "
            f"state must come from pane_active_job_count()"
        )


def test_every_pane_takes_its_busy_state_from_the_one_queue_helper():
    for pane in PANES:
        assert "pane_active_job_count(" in _pane_code(pane), (
            f"{pane} pane has no queue-backed busy state"
        )


def test_the_queue_count_helper_has_exactly_one_definition():
    """One definition, three panes — never a per-pane re-derivation."""
    definitions = [
        path.name
        for path in CPP.glob("*.cc")
        if re.search(r"^int pane_active_job_count\(", path.read_text(), re.M)
    ]
    assert definitions == ["agent_ui_pane_kit_feedback.cc"], definitions
    assert "int pane_active_job_count(" in KIT_HH, "helper is not in the kit header"


def test_the_queue_helper_reads_the_same_mirror_the_queue_tab_lists():
    """`wm.mixie_queue`, walked with the clamped RNA string read.

    `RNA_property_string_get` is strcpy-shaped and overflows a fixed buffer on
    a longer value; the alloc form clamps. Same finding as the queue pane's
    `read_item_string`.
    """
    code = _code(FEEDBACK)
    assert '"mixie_queue"' in code and '"items"' in code
    assert "RNA_property_string_get_alloc(" in code
    assert "RNA_property_string_get(" not in code.replace(
        "RNA_property_string_get_alloc(", ""
    )


def _active_states(code: str) -> set[str]:
    body = code[code.index("bool queue_state_is_active(") :]
    body = body[: body.index("\n}")]
    return set(re.findall(r'STREQ\(state, "([A-Z_]+)"\)', body))


def test_the_active_state_vocabulary_is_the_queue_panes_own():
    """One vocabulary, two surfaces.

    The mirror writes ``JobState``'s own names; ``agent_ui_queue.cc`` buckets
    them into running / pending / done / failed. The non-terminal set here
    must be exactly the union of its running and pending buckets — an invented
    state simply never matches and the button silently stops reporting.
    """
    active = _active_states(_code(FEEDBACK))
    assert active == {
        "PENDING",
        "PAUSED_AUTH",
        "RUNNING_SUBMIT",
        "RUNNING_POLL",
        "RUNNING_DOWNLOAD",
    }, active

    queue_code = _code(QUEUE_CC)
    for state in active:
        assert f'"{state}"' in queue_code, (
            f"{state} is not a state agent_ui_queue.cc knows"
        )
    for terminal in ("SUCCESS", "FAILED", "CANCELLED"):
        assert terminal not in active, f"{terminal} is terminal, never active"


def test_the_queue_helper_matches_a_jobs_three_identities():
    """`service`, `feature_key` and `origin_capability_key`.

    Which field carries the pane's key depends on the feature (a job_type, a
    FeatureQueue key, or the capability a composite workflow was launched
    from), so narrowing to one silently under-reports on the others.
    """
    code = _code(FEEDBACK)
    for field in ("service", "feature_key", "origin_capability_key"):
        assert f'"{field}"' in code, f"the queue match ignores {field}"


def test_an_unidentified_service_counts_any_active_job():
    """Falling back to "something is running" beats reporting nothing."""
    code = _code(FEEDBACK)
    assert "match_any" in code, (
        "no fallback for a pane that cannot identify its service"
    )


def test_no_pane_hardcodes_a_3d_service_slug_for_the_count():
    """The 3D pane passes whatever mode it resolved, never a slug table."""
    code = _code(PANE_SOURCES["agent_ui_tab3d.cc"])
    call = re.search(r"pane_active_job_count\(([^)]*)\)", code)
    assert call, "the 3D pane does not call pane_active_job_count"
    assert '"' not in call.group(1), (
        f"the 3D pane hardcodes a service slug: {call.group(0)}"
    )


def test_no_pane_clears_the_prompt_on_submit():
    """Users iterate on a prompt and regenerate.

    Feedback comes from the button and the report line; destroying the text
    the user just typed is not feedback.
    """
    for pane in PANES:
        code = _pane_code(pane)
        assert not re.search(r'RNA_\w*string_set\([^;]*"prompt"', code), (
            f"{pane} pane writes the prompt property"
        )


# -------------------------------------------------------------------------
# B. The report line


def test_every_pane_draws_the_one_report_line():
    for pane in PANES:
        assert "pane_report_line_draw(" in _pane_code(pane), (
            f"{pane} pane never surfaces an operator report; a refusal like "
            f'"No image selected in moodboard" would be silent'
        )


def test_the_report_painter_has_exactly_one_definition():
    definitions = [
        path.name
        for path in CPP.glob("*.cc")
        if re.search(r"^bool pane_report_line_draw\(", path.read_text(), re.M)
    ]
    assert definitions == ["agent_ui_pane_kit_feedback.cc"], definitions
    assert "bool pane_report_line_draw(" in KIT_HH


def test_the_report_line_consumes_the_dedicated_pane_message_channel():
    code = _code(FEEDBACK)
    for prop in CHANNEL_PROPS:
        assert f'"{prop}"' in code, f"the message line never reads {prop}"


def test_the_report_line_never_reads_the_global_report_list_again():
    """The bug this channel exists to fix.

    Blender's global report list collects reports from EVERYTHING in the app,
    Mixar's own agent running sandboxed Blender scripts included, so a pane
    sourced from it painted unrelated bpy script output above the user's
    prompt. Unrelated app activity must never appear in a generation pane.
    """
    code = _code(FEEDBACK)
    for banned in ("mixar_last_report", "mixar_report_count", "RPT_ERROR_ALL",
                   "RPT_WARNING_ALL"):
        assert banned not in code, (
            f"the message line is back on the global report list ({banned})"
        )


def test_the_global_report_channel_is_gone_from_the_rna_overlay():
    """Deleted, not merely unused — an unused surface invites a rewiring."""
    rna = (
        ROOT / "src/source/blender/makesrna/intern/rna_wm_mixar.cc"
    ).read_text()
    body = rna[rna.index("#include"):]
    for banned in ("mixar_last_report", "mixar_report_count"):
        assert banned not in body, (
            f"{banned} still exists in the RNA overlay outside the header note"
        )
    # The header must record WHY, so nobody re-adds it for the same reason.
    header = rna[: rna.index("#include")].lower()
    assert "removed" in header and "agent" in header, (
        "the file header does not record why the report channel was removed"
    )


def test_a_missing_channel_property_draws_nothing():
    """These properties live in a module this pane does not own.

    A build (or a startup ordering) without them must degrade to drawing
    nothing, never to an empty line or a crash — hence the negative sentinel
    out of the serial read and the immediate bail.
    """
    code = _code(FEEDBACK)
    body = code[code.index("bool pane_report_line_draw(") :]
    read = body.index('"mixar_pane_message_serial"')
    guard = body.index("serial < 0", read)
    ret = body.index("return false;", guard)
    assert guard < ret, "a missing mixar_pane_message_serial does not bail out"


def _report_body() -> str:
    code = _code(FEEDBACK)
    body = code[code.index("bool pane_report_line_draw(") :]
    return body[: body.index("\n}")]


def test_the_report_line_gates_on_the_serial_not_a_count():
    """A repeat is news; a redraw is not.

    The writer bumps the serial on EVERY write, the same text included, so
    pressing Generate again and being refused again restarts the freshness
    clock. A count of anything (reports, writes seen elsewhere) cannot say
    that, and a plain text comparison cannot either.
    """
    body = _report_body()
    assert "serial" in body, "the painter does not read a serial at all"
    assert re.search(r"serial\s*>\s*g_msg_seen_serial", body), (
        "the message line does not gate on the serial increasing"
    )
    assert "count" not in body, (
        "the message line still gates on a count somewhere"
    )


def test_the_report_line_is_gated_on_freshness():
    """Serial + timestamp, not "draw whatever the channel holds".

    Without the gate the newest message would sit on the pane forever — long
    after it stopped describing anything the user just did.
    """
    code = _code(FEEDBACK)
    assert "BLI_time_now_seconds()" in code
    assert "PANE_MSG_TTL_S" in code and "PANE_MSG_TTL_S" in KIT_HH
    body = _report_body()
    assert re.search(r"g_msg_stamp\)\s*>\s*PANE_MSG_TTL_S", body), (
        "the message line never expires"
    )


def test_the_first_paint_cannot_show_a_stale_message():
    """The channel is not empty at startup.

    A pane opened long after a message was written (or after a file load into
    the same session) must ADOPT the serial and draw nothing. Only a later
    increase is news.
    """
    code = _code(FEEDBACK)
    assert re.search(r"g_msg_seen_serial\s*=\s*-1;", code), (
        "the seen-serial static has no 'nothing seen yet' sentinel"
    )
    body = _report_body()
    first = body.index("g_msg_seen_serial < 0")
    ret = body.index("return false;", first)
    draw = body.index("pane_label_left(")
    assert first < ret < draw, (
        "the first paint reaches the painter instead of adopting the serial"
    )


def test_the_report_line_is_coloured_by_severity():
    """Error red, warning amber, info dim — from the channel's own level."""
    code = _code(FEEDBACK)
    assert "PANE_MSG_LEVEL_ERROR" in code and "PANE_MSG_LEVEL_WARNING" in code
    assert "PANE_COL_MSG_ERROR" in code and "PANE_COL_MSG_WARN" in code
    for token in ("PANE_COL_MSG_ERROR", "PANE_COL_MSG_WARN"):
        colour = re.search(rf"#define {token} \{{([^}}]*)\}}", KIT_HH)
        assert colour, f"{token} is not defined in the kit header"
        # A three-value initializer zero-fills alpha and draws invisibly.
        assert len(colour.group(1).split(",")) == 4, (
            f"{token} must state its alpha explicitly"
        )


def test_the_report_line_elides_with_the_kits_utf8_aware_fitter():
    assert "pane_fit_text(" in _code(FEEDBACK), (
        "a long report would run off the pane instead of eliding"
    )


def test_the_report_line_scales_with_the_island_unit():
    """`u`, never AGENT_DU: AGENT_DU is island-width independent, so a label
    sized with it changes size relative to everything around it the moment the
    bubble is resized."""
    code = _code(FEEDBACK)
    assert "AGENT_DU" not in code
    assert re.search(r"PANE_MSG_FONT \* u", code), (
        "the report line's font is not in island units"
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
        if re.search(r"^def set_pane_message\(", path.read_text(), re.M)
    ]
    assert definitions == ["pane_message_props.py"], definitions

    for path in PY.rglob("*.py"):
        if path == CHANNEL_PY:
            continue
        source = path.read_text()
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
        lines = len((CPP / name).read_text().splitlines())
        assert lines <= 500, f"{name} is {lines} lines"


# ---------------------------------------------------------------------------
# A live job is information, not a lock.


def _pane(name: str) -> str:
    from pathlib import Path

    return (
        Path(__file__).resolve().parents[1]
        / "src/source/blender/editors/space_agent_bubble"
        / name
    ).read_text()


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
