# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Source-level pins for native crash guards that have no runtime test.

The C++ overlay cannot be compiled or driven from the standalone suite, so
these tests read the sources and pin the shape of each guard: the bubble
never resizes its window from inside a draw pass, every fixed-buffer slot
string read is bounded, both chat spaces null their runtime pointer on
file read, and the Director timeline's static timer has an exit hook.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUBBLE = ROOT / "src/source/blender/editors/space_agent_bubble/space_agent_bubble.cc"
SLOTS = ROOT / "src/source/blender/editors/space_mixie_chat/mixie_chat_slots.cc"
UI_TYPES = ROOT / "src/source/blender/editors/space_mixie_chat/mixie_chat_ui_types.hh"
SLOT_PROPS = ROOT / "src/scripts/mixar/modules/space_mixie_chat/ui/properties/chat_slot_types.py"
CHAT_SPACE = ROOT / "src/source/blender/editors/space_mixie_chat/space_mixie_chat.cc"
TIMELINE = ROOT / "src/source/blender/editors/space_view3d/view3d_director_timeline.cc"
MESSAGES = ROOT / "src/source/blender/editors/space_mixie_chat/mixie_chat_messages.cc"


def _fn(src: str, name: str) -> str:
    start = src.index(name + "(")
    start = src.rindex("\n", 0, start)
    depth = 0
    i = src.index("{", start)
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[start:j + 1]
    raise AssertionError(name)


def test_bubble_draw_and_layout_only_request_a_resize():
    src = BUBBLE.read_text()
    draw = _fn(src, "static void agent_bubble_footer_region_draw")
    layout = _fn(src, "static void agent_bubble_footer_region_layout")
    for block in (draw, layout):
        assert "agent_bubble_sync_footer_window_size(C, region, /*from_draw=*/true)" in block
        assert "bubble_force_size_and_refresh(" not in block
        assert "ED_screen_refresh(" not in block
    sync = _fn(src, "static void agent_bubble_sync_footer_window_size")
    # The draw-time branch records and notifies; only the exec branch resizes.
    assert "if (from_draw) {\n      agent_bubble_request_resize(C, target_height, height_floor);" in sync
    request = _fn(src, "static void agent_bubble_request_resize")
    assert "WM_event_add_notifier(C, NC_WINDOW, nullptr);" in request
    assert "Mixar_WindowForceSize" not in request and "ED_screen_refresh" not in request


def test_bubble_resize_is_applied_from_the_footer_listener_by_tagging():
    src = BUBBLE.read_text()
    assert "art->listener = agent_bubble_footer_region_listener;" in src
    listener = _fn(src, "static void agent_bubble_footer_region_listener")
    assert "bubble_apply_window_size(\n      nullptr, nullptr, win" in listener
    apply = _fn(src, "static void bubble_apply_window_size")
    # Without a context the screen is tagged; ED_screen_ensure_updated refreshes.
    assert "screen->do_refresh = true;" in apply
    assert "if (C != nullptr && wm != nullptr) {\n      ED_screen_refresh(C, wm, w);" in apply
    # Operator exec keeps the immediate form.
    exec_fn = _fn(src, "static wmOperatorStatus mixar_bubble_sync_attachment_size_exec")
    assert "/*from_draw=*/false" in exec_fn


def test_slot_string_reads_are_bounded():
    src = SLOTS.read_text()
    raw = re.findall(r"RNA_property_string_get\(&(\w+), (g_\w+\.\w+), (\S+)\);", src)
    # Only length-guarded fixed-id reads may stay raw (bubble_id / todo.id
    # style, each behind an explicit `< sizeof` check).
    for _ptr, prop, dst in raw:
        assert prop in ("g_todo_props.item_id",), (prop, dst)
    for field in ("label", "value", "image"):
        assert f"read_rna_string_bounded(&action_ptr, g_action_props.{field}, action.{field}, sizeof(action.{field}))" in src
    assert "read_rna_string_bounded(&todo_ptr, g_todo_props.text, todo.text, sizeof(todo.text))" in src
    for field in ("url", "alt", "caption", "thumbnail_url", "local_path"):
        assert f"read_rna_string_bounded(&image_ptr, g_image_props.{field}, img.{field}, sizeof(img.{field}))" in src


def test_image_slot_local_path_maxlen_mirrors_the_c_buffer():
    props = SLOT_PROPS.read_text()
    block = props[props.index("local_path: StringProperty("):]
    block = block[: block.index("\n    )")]
    m = re.search(r"maxlen=(\d+)", block)
    assert m, "local_path must declare a maxlen"
    types = UI_TYPES.read_text()
    c = re.search(r"char local_path\[(\d+)\];", types)
    assert c and int(m.group(1)) == int(c.group(1))


def test_chat_spaces_null_runtime_on_read():
    for path, struct in ((CHAT_SPACE, "SpaceMixieChat"), (BUBBLE, "SpaceAgentBubble")):
        src = path.read_text()
        assert "st->blend_read_data = " in src
        name = re.search(r"static void (\w+_blend_read_data)\(", src).group(1)
        read = _fn(src, "static void " + name)
        assert struct in read and "->runtime = nullptr;" in read


def test_director_timeline_timer_has_a_region_exit():
    src = TIMELINE.read_text()
    assert "art->exit = director_timeline_region_exit;" in src
    exit_fn = _fn(src, "static void director_timeline_region_exit")
    assert "WM_event_timer_remove(wm, nullptr, g_playback_redraw_timer);" in exit_fn
    assert "g_playback_redraw_timer = nullptr;" in exit_fn


def test_code_copy_collector_forgets_a_freed_runtime():
    src = MESSAGES.read_text()
    free_fn = _fn(src, "void mixie_chat_free_runtime")
    assert free_fn.index("mixie_chat_code_hits_forget(rt);") < free_fn.index("MEM_delete(rt);")
