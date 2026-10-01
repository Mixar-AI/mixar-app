# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""An OS file drop anywhere on the agent island attaches and boards it.

Dropping images from Explorer / Finder onto the island must attach them to
the chat composer and place them on the moodboard, whatever the island is
showing: any tab, the tab strip, the transcript, the reference column or the
composer. A pane tab switches to Agent on release, like the resting capsule,
so a pill is never added to a hidden composer. The native dropbox is C++ and
the Python operator is a MagicMock subclass under test, so both are pinned
at source level.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRAGDROP = ROOT / "src/source/blender/editors/space_mixie_chat/mixie_chat_dragdrop.cc"
IMAGE_OPS = ROOT / "src/scripts/mixar/modules/space_mixie_chat/ui/operators/image_ops.py"


def _body(src: str, signature: str) -> str:
    start = src.index(signature)
    return src[start:src.index("\n}\n", start)]


def _poll() -> str:
    return _body(DRAGDROP.read_text(encoding="utf-8"), "static bool mixie_chat_image_drop_poll(")


def _exec() -> str:
    return _body(DRAGDROP.read_text(encoding="utf-8"),
                 "static wmOperatorStatus mixie_chat_drop_image_exec(")


def test_poll_accepts_the_whole_attachment_destination():
    body = _poll()
    # The island's tab strip is no longer refused; the status pill above an
    # open island and a window mid-minimise are excluded by window identity.
    assert "RGN_TYPE_HEADER" not in body
    assert "ED_agent_bubble_is_attachment_destination(CTX_wm_window(C))" in body


def test_pane_tabs_take_only_os_file_drops_and_fail_closed():
    body = _poll()
    branch = body[body.index("!ED_agent_bubble_tab_shows_chat(C, false)"):]
    branch = branch[:branch.index("\n  }\n")]
    assert "drag->type != WM_DRAG_PATH" in branch, (
        "an in-app Image-ID drag on a generation pane must stay refused")
    assert "mixie_chat_drop_agent_tab(C" in branch, (
        "before Python registers the tab property there is no composer to show")
    assert "return false;" in branch


def test_movie_refusal_still_runs_on_every_tab():
    body = _poll()
    path = body[body.index("if (drag->type == WM_DRAG_PATH)"):]
    assert path.index("FILE_TYPE_MOVIE") < path.index("return true;")


def test_pane_tab_drop_shows_agent_before_attaching():
    body = _exec()
    switch = body.index("else if (CTX_wm_area(C) && CTX_wm_area(C)->spacetype == SPACE_AGENT_BUBBLE")
    assert "mixie_chat_drop_show_agent_tab(C);" in body[switch:]
    assert switch < body.index('WM_operator_properties_create("MIXIE_CHAT_OT_add_image_from_file")')
    # The resting capsule shares the same switch before its restore.
    pill = body.index("if (ED_agent_bubble_is_resting_pill(C))")
    assert body.index("mixie_chat_drop_show_agent_tab(C);", pill) < body.index(
        "MIXAR_OT_bubble_restore")


def test_agent_tab_switch_goes_through_rna_update():
    src = DRAGDROP.read_text(encoding="utf-8")
    body = _body(src, "static void mixie_chat_drop_show_agent_tab(")
    # The update callback sets the chat mode and repaints, as a tab click does.
    assert "RNA_property_enum_set(&wm, tab, agent);" in body
    assert body.index("RNA_property_enum_set") < body.index("RNA_property_update(C, &wm, tab);")


def test_dropped_file_attaches_then_boards():
    src = IMAGE_OPS.read_text(encoding="utf-8")
    body = src[src.index("class MIXIE_CHAT_OT_add_image_from_file"):
               src.index("class MIXIE_CHAT_OT_add_image_from_blend")]
    add = body.index("attachment.image_source = 'FILE'")
    assert body.index("mirror_attachment_to_moodboard(scene, filepath, 'FILE')", add) > add
