# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A scene tab names itself after its first prompt (parallel scenes)."""

from types import SimpleNamespace

import pytest

from mixar.modules.space_mixie_chat.core import scene_naming


@pytest.mark.parametrize("name, default", [
    ("Scene", True), ("Scene.001", True), ("Scene 7", True), ("Scene 12", True),
    ("Kitchen", False), ("Scene kitchen", False), ("scene", False), ("Scene.1", False),
])
def test_default_tab_names(name, default):
    assert scene_naming.is_default_tab_name(name) is default


@pytest.mark.parametrize("prompt, title", [
    ("Create a red cube named QA_A", "Red Cube Named QA_A"),
    ("please build me a small kitchen table with four chairs", "Small Kitchen Table"),
    ("Create a blue uv sphere named T2_Sphere", "Blue Uv Sphere"),
    ("Build a bookshelf with two shelves and five books", "Bookshelf With Two"),
    ("UV unwrap this creature and pack the islands", "UV Unwrap This Creature"),
    ("a", "A"),
    ("", ""),
    ("!!!", ""),
    ("hello", "Hello"),
    ("first line here\nsecond line", "First Line Here"),
])
def test_titles_from_prompts(prompt, title):
    assert scene_naming.title_for_prompt(prompt) == title


def test_a_long_word_is_cut_rather_than_dropped():
    assert scene_naming.title_for_prompt("Supercalifragilisticexpialidocious tower") == \
        "Supercalifragilisticexpi"


def _msg(sender, text="x", loader=False):
    return SimpleNamespace(sender=sender, text=text, loader_visible=loader)


def _scene(name, messages=()):
    return SimpleNamespace(name=name, mixie_session_id="sess", mixie_chat_messages=list(messages))


def test_a_default_tab_takes_its_first_prompt_as_its_name(monkeypatch):
    logged = []
    monkeypatch.setattr(scene_naming, "slog", lambda *a, **kw: logged.append((a, kw)))
    # The optimistic user bubble and the agent's loader placeholder are already there.
    scene = _scene("Scene.002", [_msg("USER"), _msg("AGENT", text="", loader=True)])
    assert scene_naming.auto_name_tab(scene, "Build a lighthouse on a rock") == "Lighthouse On A Rock"
    assert scene.name == "Lighthouse On A Rock"
    assert logged and logged[0][0][0] == "tab.autoname"


def test_a_renamed_tab_and_a_later_prompt_keep_the_name(monkeypatch):
    monkeypatch.setattr(scene_naming, "slog", lambda *a, **kw: None)
    named = _scene("Kitchen", [_msg("USER")])
    assert scene_naming.auto_name_tab(named, "Build a lighthouse") == ""
    assert named.name == "Kitchen"
    later = _scene("Scene", [_msg("USER"), _msg("AGENT"), _msg("USER")])
    assert scene_naming.auto_name_tab(later, "Build a lighthouse") == ""
    assert later.name == "Scene"
    second = _scene("Scene", [_msg("USER"), _msg("USER")])
    assert scene_naming.auto_name_tab(second, "Build a lighthouse") == ""
    assert scene_naming.auto_name_tab(_scene("Scene", [_msg("USER")]), "") == ""
