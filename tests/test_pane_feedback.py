# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Native queue feedback and report-line contracts for generation panes."""
import re

from pane_feedback_contract import (
    ROOT,
    CPP,
    FEEDBACK,
    KIT_HH,
    QUEUE_CC,
    CHANNEL_PROPS,
    PANE_SOURCES,
    PANES,
    _code,
    _pane_code,
)

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
        if re.search(r"^int pane_active_job_count\(", path.read_text(encoding="utf-8"), re.M)
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

    The mirror writes ``JobState``'s own names; ``agent_ui_queue_data.cc`` buckets
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
            f"{state} is not a state agent_ui_queue_data.cc knows"
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
        if re.search(r"^bool pane_report_line_draw\(", path.read_text(encoding="utf-8"), re.M)
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
    ).read_text(encoding="utf-8")
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
