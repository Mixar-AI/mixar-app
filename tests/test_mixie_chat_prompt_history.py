# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Up in the chat composer recalls the prompts the user already sent.

Up on the composer's first line shows the previous USER message of this chat
(newest first, walking back on each press); Down on its last line walks
forward and finally restores the draft that was there before the first Up.
The navigation rules live in a standard-library header that the harness
compiles as shipped; the text-edit wiring is pinned at source level because
it lives inside Blender's native text handler.
"""
import functools
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDITORS = ROOT / "src/source/blender/editors"
CHAT = EDITORS / "space_mixie_chat"
HARNESS_SRC = ROOT / "tests/prompt_history_harness.cc"

HANDLERS = (EDITORS / "interface/interface_handlers.cc").read_text(encoding="utf-8")
GLUE = (CHAT / "mixie_chat_prompt_history.cc").read_text(encoding="utf-8")
CMAKE = (CHAT / "CMakeLists.txt").read_text(encoding="utf-8")


@functools.lru_cache(maxsize=1)
def _harness() -> Path:
    cxx = shutil.which("c++") or shutil.which("clang++")
    assert cxx, "need c++ or clang++ to run the prompt history harness"
    binary = Path(tempfile.mkdtemp(prefix="mixie-prompt-history-")) / "harness"
    subprocess.check_call(
        [cxx, "-std=c++17", "-O0", "-Wall", "-Werror", f"-I{CHAT}", str(HARNESS_SRC),
         "-o", str(binary)],
        cwd=str(ROOT),
    )
    return binary


def run(*script: str) -> list[tuple[bool, str]]:
    """Play key presses; one (changed, composer text) pair per up/down."""
    out = subprocess.run([str(_harness())], input="\n".join(script) + "\n",
                         capture_output=True, text=True, check=True).stdout
    rows = []
    for line in out.splitlines():
        state, _, text = line.partition("\t")
        rows.append((state == "changed", text))
    return rows


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


PROMPTS = "prompts make it red|add a sphere|make a cube"


def test_up_recalls_the_last_prompt_then_older_ones():
    assert run(PROMPTS, "up", "up", "up", "up") == [
        (True, "make it red"),
        (True, "add a sphere"),
        (True, "make a cube"),
        (False, "make a cube"),  # the oldest stays put
    ]


def test_down_walks_forward_and_restores_the_draft():
    assert run(PROMPTS, "type half-written idea", "up", "up", "down", "down", "down") == [
        (True, "make it red"),
        (True, "add a sphere"),
        (True, "make it red"),
        (True, "half-written idea"),
        (False, "half-written idea"),  # back to normal cursor movement
    ]


def test_down_without_a_recall_does_nothing():
    assert run(PROMPTS, "type draft", "down") == [(False, "draft")]


def test_no_history_leaves_the_composer_alone():
    assert run("type draft", "up", "down") == [(False, "draft"), (False, "draft")]


def test_editing_a_recalled_prompt_ends_the_walk():
    # Down no longer swaps an edited prompt away; Up starts over and keeps
    # the edit as the draft to come back to.
    assert run(PROMPTS, "up", "type make it red and shiny", "down", "up", "down") == [
        (True, "make it red"),
        (False, "make it red and shiny"),
        (True, "make it red"),
        (True, "make it red and shiny"),
    ]


def test_a_draft_equal_to_the_newest_prompt_is_not_a_dead_key():
    assert run(PROMPTS, "type make it red", "up") == [(True, "add a sphere")]


def test_each_composer_walks_on_its_own():
    assert run(PROMPTS, "up", "composer B", "down", "up") == [
        (True, "make it red"),
        (False, "make it red"),
        (True, "add a sphere"),
    ]


def test_a_transcript_cleared_mid_walk_returns_the_draft():
    assert run(PROMPTS, "type draft", "up", "prompts ", "down") == [
        (True, "make it red"),
        (True, "draft"),
    ]


def test_a_prompt_clipped_by_the_field_keeps_walking():
    assert run(PROMPTS, "up", "clip 4", "up") == [
        (True, "make it red"),
        (True, "add a sphere"),
    ]


def test_up_and_down_fall_back_to_history_only_at_the_edges():
    move = _function_body(HANDLERS, "static bool textedit_move_vertical_mixar(")
    assert move.count("return false;") == 2  # single line, and already at the edge
    textedit = _function_body(HANDLERS, "static int do_but_textedit(")
    for direction, comment in ((-1, "Up on the composer's first line"),
                               (+1, "Down on the composer's last line")):
        sign = "-1" if direction < 0 else "+1"
        hook = (f"if (!textedit_move_vertical_mixar(but, text_edit, {sign}, "
                "event->modifier & KM_SHIFT) &&\n"
                "              (event->modifier & (KM_SHIFT | KM_CTRL | KM_ALT | KM_OSKEY)) == 0)")
        assert hook in textedit
        start = textedit.index(hook)
        branch = textedit[start : textedit.index("retval = WM_UI_HANDLER_BREAK;", start)]
        assert comment in branch
        assert "ui_but_mixie_mention_scene(but)" in branch  # the chat composer only
        assert f"ui_textedit_prompt_history_step(\n                  but, text_edit, history_scene, {sign})" in branch
        # An open @-mention dropdown keeps Up/Down for its suggestions.
        key = "EVT_UPARROWKEY" if direction < 0 else "EVT_DOWNARROWKEY"
        step = f"mixie_chat_mention_step(mention_scene, {sign});"
        assert textedit.index(step) < start
        assert textedit.index(f"case {key}:") < start


def test_a_recalled_prompt_goes_through_the_normal_edit_path():
    step = _function_body(HANDLERS, "static bool ui_textedit_prompt_history_step(")
    assert "textedit_string_set(but, text_edit, text.c_str());" in step
    assert "mixie_chat_prompt_history_landed(text_edit.edit_string);" in step
    assert "but->selsta = but->selend = but->pos;" in step
    textedit = _function_body(HANDLERS, "static int do_but_textedit(")
    assert "changed = recalled_prompt = ui_textedit_prompt_history_step(" in textedit
    # Recalling "look at @Cube" must not pop the mention dropdown open.
    assert "if (!is_ime_composing && !recalled_prompt) {" in textedit


def test_history_is_the_user_messages_of_this_chat():
    collect = _function_body(GLUE, "static std::vector<std::string> prompt_history_collect(")
    assert '"mixie_chat_messages"' in collect
    assert 'prompt_history_string(&message, "text")' in collect
    assert 'prompt_history_string(&message, "content")' in collect
    assert "std::reverse(prompts.begin(), prompts.end());" in collect
    assert 'STREQ(identifier, "USER")' in GLUE


def test_sources_are_built():
    assert "  mixie_chat_prompt_history.cc\n" in CMAKE
    assert "  mixie_chat_prompt_history.hh\n" in CMAKE
