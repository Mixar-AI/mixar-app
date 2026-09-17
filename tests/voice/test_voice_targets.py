# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Where a transcript lands, and what it must never do on the way there.

Three failures this pins, all of them silent if they regress:

- REPLACING the field instead of appending. Someone types half a sentence,
  dictates the rest, and the typed half disappears.
- Leaving the submit marker in. The chat composer's update callback reads
  ``\\x1f`` as "Enter was pressed" and SENDS the message, so a transcript
  carrying one would fire mid-insert.
- Writing into a neighbouring field when the target is gone. A node deleted
  while its words were in flight must drop them, not paste them somewhere
  else.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock  # noqa: E402

install_bpy_mock()

from mixar.modules.voice.core import targets  # noqa: E402
from mixar.modules.voice.constants import (  # noqa: E402
    SUBMIT_MARKER,
    TARGET_CHAT,
)


class _Node:
    def __init__(self, node_id, prompt=""):
        self.node_id = node_id
        self.prompt = prompt


class _Tab:
    def __init__(self, prompt=""):
        self.prompt = prompt


def _scene(chat="", nodes=(), tabs=None):
    sidebar = SimpleNamespace(**(tabs or {}))
    return SimpleNamespace(
        mixie_chat_input=chat,
        mixie_moodboard_action_nodes=list(nodes),
        mixie_moodboard_sidebar=sidebar,
    )


# -- target shapes ---------------------------------------------------------


def test_every_shape_the_ui_can_build_is_addressable():
    assert targets.is_valid_target(TARGET_CHAT)
    assert targets.is_valid_target(targets.target_for_node("abc123"))
    assert targets.is_valid_target(
        targets.target_for_tab("MixieMoodboardTabImageGenProps")
    )


def test_a_malformed_or_unknown_target_is_refused_rather_than_guessed():
    assert not targets.is_valid_target("")
    assert not targets.is_valid_target("node:")
    assert not targets.is_valid_target("tab:NotARealTabProps")
    assert not targets.is_valid_target("composer")


def test_the_tab_map_matches_the_enter_to_generate_table():
    """A tab reachable by Enter must be reachable by the mic, and vice versa.

    Both tables are keyed on the owning PropertyGroup's RNA identifier. If one
    gains a tab and the other does not, that tab silently loses half its
    affordances — a prompt you can dictate into but not submit, or the reverse.
    """
    from mixar.modules.moodboard.core.prompt_submit import PROMPT_TAB_DISPATCH

    assert set(targets._TAB_ATTRIBUTES) == set(PROMPT_TAB_DISPATCH)


# -- insertion -------------------------------------------------------------


def test_a_transcript_is_appended_to_what_the_user_already_typed():
    scene = _scene(chat="make it")
    assert targets.insert_transcript(scene, TARGET_CHAT, "taller please")
    assert scene.mixie_chat_input == "make it taller please"


def test_trailing_whitespace_is_not_doubled():
    scene = _scene(chat="make it ")
    targets.insert_transcript(scene, TARGET_CHAT, "taller")
    assert scene.mixie_chat_input == "make it taller"


def test_an_empty_field_takes_the_transcript_verbatim():
    scene = _scene(chat="")
    targets.insert_transcript(scene, TARGET_CHAT, "a red chair")
    assert scene.mixie_chat_input == "a red chair"


def test_the_submit_marker_is_stripped_before_the_text_reaches_the_composer():
    scene = _scene(chat="")
    targets.insert_transcript(scene, TARGET_CHAT, f"send this{SUBMIT_MARKER}")
    assert SUBMIT_MARKER not in scene.mixie_chat_input
    assert scene.mixie_chat_input == "send this"


def test_a_node_prompt_is_written_by_id():
    first = _Node("n1", "existing")
    second = _Node("n2")
    scene = _scene(nodes=(first, second))
    targets.insert_transcript(scene, targets.target_for_node("n2"), "a blue cube")
    assert second.prompt == "a blue cube"
    assert first.prompt == "existing"


def test_a_tab_prompt_is_written_through_its_sidebar_attribute():
    tab = _Tab("wood")
    scene = _scene(tabs={"tab_imagegen": tab})
    targets.insert_transcript(
        scene, targets.target_for_tab("MixieMoodboardTabImageGenProps"), "and metal"
    )
    assert tab.prompt == "wood and metal"


# -- the target that went away ---------------------------------------------


def test_a_deleted_node_drops_the_transcript_instead_of_writing_elsewhere():
    survivor = _Node("n1", "keep me")
    scene = _scene(chat="chat text", nodes=(survivor,))
    assert not targets.insert_transcript(
        scene, targets.target_for_node("deleted"), "these words"
    )
    assert survivor.prompt == "keep me"
    assert scene.mixie_chat_input == "chat text"


def test_a_missing_scene_drops_the_transcript():
    assert not targets.insert_transcript(None, TARGET_CHAT, "words")


def test_an_empty_transcript_is_a_no_op_that_still_reports_success():
    """Silence is not a failed insert — there was simply nothing to write."""
    scene = _scene(chat="untouched")
    assert targets.insert_transcript(scene, TARGET_CHAT, "   ")
    assert scene.mixie_chat_input == "untouched"
