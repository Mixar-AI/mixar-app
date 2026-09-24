# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Hold Option/Alt dictates; release finishes. Click-to-talk and typed V stay put."""
import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
KEYMAP_PY = ROOT / "src/scripts/mixar/modules/space_mixie_chat/ui/keymap.py"
VOICE_OPS = ROOT / "src/scripts/mixar/modules/space_mixie_chat/ui/operators/voice_ops.py"
HANDLERS_CC = ROOT / "src/source/blender/editors/interface/interface_handlers.cc"
BUBBLE_CC = ROOT / "src/source/blender/editors/space_agent_bubble/space_agent_bubble.cc"

from mixar.modules.space_mixie_chat.core import voice  # noqa: E402
from mixar.modules.space_mixie_chat.ui.operators import voice_ops  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_hold(monkeypatch):
    monkeypatch.setattr(voice, "_status", lambda _text: None)
    monkeypatch.setattr(voice, "_toast", lambda _level, _message: None)
    voice._session = None
    voice._ptt_owned = False
    yield
    voice._session = None
    voice._ptt_owned = False


def test_begin_owns_the_session_and_a_repeat_does_not_start_another(monkeypatch):
    started = []

    def fake_start(context):
        started.append(context)
        voice._session = object()
        return "started"

    monkeypatch.setattr(voice, "start", fake_start)
    assert voice.push_to_talk_begin("ctx") == "started"
    assert voice.push_to_talk_owned() is True
    assert voice.push_to_talk_begin("ctx") == "holding"
    assert started == ["ctx"]


def test_failed_start_does_not_own_the_hold(monkeypatch):
    monkeypatch.setattr(voice, "start", lambda _context: "unavailable")
    assert voice.push_to_talk_begin(None) == "unavailable"
    assert voice.push_to_talk_owned() is False


def test_click_session_is_busy_and_release_does_not_stop_it(monkeypatch):
    voice._session = object()
    started = []
    stopped = []
    monkeypatch.setattr(voice, "start", lambda _context: started.append(1) or "started")
    monkeypatch.setattr(voice, "stop", lambda: stopped.append(1))
    assert voice.push_to_talk_begin(None) == "busy"
    assert started == []
    assert voice.push_to_talk_owned() is False
    assert voice.push_to_talk_end() == "ignored"
    assert stopped == []


def test_release_stops_once_and_a_second_release_is_ignored(monkeypatch):
    voice._ptt_owned = True
    voice._session = object()
    stopped = []
    monkeypatch.setattr(voice, "stop", lambda: stopped.append(1))
    assert voice.push_to_talk_end() == "stopped"
    assert voice.push_to_talk_owned() is False
    assert voice.push_to_talk_end() == "ignored"
    assert stopped == [1]


def test_escape_discards_without_stopping(monkeypatch):
    voice._ptt_owned = True
    voice._session = object()
    cancelled = []
    monkeypatch.setattr(voice, "cancel", lambda: cancelled.append(1))
    monkeypatch.setattr(voice, "stop", lambda: (_ for _ in ()).throw(AssertionError("stop")))
    assert voice.push_to_talk_end(discard=True) == "cancelled"
    assert cancelled == [1]
    assert voice.push_to_talk_owned() is False


def test_finish_clears_a_hold_that_ended_on_its_own(monkeypatch):
    voice._ptt_owned = True
    voice._finish(app_exit=True)
    assert voice.push_to_talk_owned() is False


def test_stop_failure_still_releases_the_hold(monkeypatch):
    voice._ptt_owned = True
    voice._session = object()
    finished = []
    monkeypatch.setattr(voice, "stop", lambda: (_ for _ in ()).throw(RuntimeError("mic")))
    monkeypatch.setattr(voice, "_finish", lambda app_exit=False: finished.append(app_exit))
    assert voice.push_to_talk_end() == "stopped"
    assert finished == [False]
    assert voice.push_to_talk_owned() is False


def _function(tree, name):
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(name)


def _class(tree, name):
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(name)


def _method(cls, name):
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(name)


def _returned_sets(fn):
    found = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Set):
            continue
        values = []
        for elt in node.value.elts:
            assert isinstance(elt, ast.Constant)
            values.append(elt.value)
        found.append(frozenset(values))
    return found


def test_operators_register_only_where_voice_exists():
    tree = ast.parse(VOICE_OPS.read_text(encoding="utf-8"))
    classes = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "classes" for target in node.targets
        ):
            classes = node.value
    assert isinstance(classes, ast.IfExp)
    assert isinstance(classes.test, ast.Name) and classes.test.id == "VOICE_INPUT_SUPPORTED"
    names = [elt.id for elt in classes.body.elts]
    assert names == [
        "MIXIE_CHAT_OT_voice_toggle",
        "MIXIE_CHAT_OT_voice_push_to_talk",
        "MIXIE_CHAT_OT_voice_push_to_talk_release",
        "MIXIE_CHAT_OT_voice_field_cancel",
    ]
    assert isinstance(classes.orelse, ast.Tuple) and classes.orelse.elts == []
    if sys.platform not in {"darwin", "win32"}:
        assert voice_ops.classes == ()


def test_keymap_only_finishes_owned_holds_and_preserves_global_v():
    source = KEYMAP_PY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assign = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "_VOICE_PTT_KEYMAPS"
    )
    maps = ast.literal_eval(assign.value)
    assert maps == (
        ("User Interface", "EMPTY", "WINDOW"),
        ("Agent Chat", "AGENT_BUBBLE", "WINDOW"),
        ("Window", "EMPTY", "WINDOW"),
    )
    fn = _function(tree, "_register_voice_push_to_talk")
    guarded = any(
        isinstance(node, ast.If)
        and isinstance(node.test, ast.UnaryOp)
        and isinstance(node.test.op, ast.Not)
        and isinstance(node.test.operand, ast.Name)
        and node.test.operand.id == "VOICE_INPUT_SUPPORTED"
        for node in fn.body
    )
    assert guarded
    idnames = set()
    values = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "new":
            continue
        keywords = {kw.arg for kw in node.keywords}
        if "type" not in keywords:
            continue
        by_name = {kw.arg: kw.value for kw in node.keywords}
        assert isinstance(by_name["type"], ast.Constant) and by_name["type"].value == "LEFT_ALT"
        assert isinstance(by_name["head"], ast.Constant) and by_name["head"].value is True
        assert isinstance(by_name["repeat"], ast.Constant) and by_name["repeat"].value is False
        assert keywords.isdisjoint({"ctrl", "shift", "alt", "oskey"})
        assert by_name["any"].value is True
        assert isinstance(node.args[0], ast.Name)
        idnames.add(node.args[0].id)
        assert isinstance(by_name["value"], ast.Name)
        values.add(by_name["value"].id)
    assert idnames == {"idname"}
    assert values == {"value"}
    body = ast.get_source_segment(source, fn)
    assert "mixie_chat.voice_push_to_talk" in body
    assert "mixie_chat.voice_push_to_talk_release" in body
    assert "'PRESS'" not in body and "'RELEASE'" in body


def test_release_discard_is_a_registered_boolean():
    tree = ast.parse(VOICE_OPS.read_text(encoding="utf-8"))
    cls = _class(tree, "MIXIE_CHAT_OT_voice_push_to_talk_release")
    prop = next(node for node in cls.body if isinstance(node, ast.AnnAssign))
    assert prop.target.id == "discard"
    assert isinstance(prop.annotation, ast.Call)
    assert not any(isinstance(node, ast.ImportFrom) and node.module == "__future__"
                   for node in tree.body)


def test_native_handler_owns_tap_hold_and_result_insertion():
    source = HANDLERS_CC.read_text(encoding="utf-8")
    native = (HANDLERS_CC.parent / "interface_text_dictation.cc").read_text()
    assert "text_dictation_event(" in source
    assert "text_dictation_end(C, data->wm, win" in source
    assert "textedit_insert_buf(but, text_edit, dictation.insert.c_str()" in source
    assert "HOLD_SECONDS = 0.30" in native
    assert "const bool trigger = event->type == EVT_LEFTALTKEY" in native
    assert "EVT_RIGHTALTKEY" not in native
    assert "EVT_VKEY" not in native
    assert "press && !trigger" in native
    assert "state.suppress_repeats = suppress" in native
    release = native[native.index("  if (release) {"):]
    assert 'const bool release = trigger && event->val == KM_RELEASE;' in native
