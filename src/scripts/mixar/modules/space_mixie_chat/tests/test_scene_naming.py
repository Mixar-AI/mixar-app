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
    ("please build me a small kitchen table with four chairs", "Small Kitchen Table With"),
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


def _scene(name, session=""):
    return SimpleNamespace(name=name, mixie_session_id=session)


def test_a_default_tab_takes_its_first_prompt_as_its_name(monkeypatch):
    logged = []
    monkeypatch.setattr(scene_naming, "slog", lambda *a, **kw: logged.append((a, kw)))
    scene = _scene("Scene.002")
    assert scene_naming.auto_name_tab(scene, "Build a lighthouse on a rock") == "Lighthouse On A Rock"
    assert scene.name == "Lighthouse On A Rock"
    assert logged and logged[0][0][0] == "tab.autoname"


def test_a_renamed_tab_and_a_tab_with_a_session_keep_their_names(monkeypatch):
    monkeypatch.setattr(scene_naming, "slog", lambda *a, **kw: None)
    named = _scene("Kitchen")
    assert scene_naming.auto_name_tab(named, "Build a lighthouse") == ""
    assert named.name == "Kitchen"
    busy = _scene("Scene", session="sess-1")
    assert scene_naming.auto_name_tab(busy, "Build a lighthouse") == ""
    assert busy.name == "Scene"
    assert scene_naming.auto_name_tab(_scene("Scene"), "") == ""
