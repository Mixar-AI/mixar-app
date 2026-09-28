# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Speaker toggle: operator branches and the topbar gate read the persisted config.

bpy is a MagicMock outside Blender, so the operator and draw functions are lifted
from source with ``ast`` and executed against fakes of the config getters.
"""

import ast
from pathlib import Path
import textwrap
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "src/scripts/mixar/modules/space_mixie_chat"
OPS = (CHAT / "ui/operators/notification_ops.py").read_text(encoding="utf-8")
PROPS = (CHAT / "ui/properties/notification_props.py").read_text(encoding="utf-8")
TOPBAR = (CHAT / "ui/topbar.py").read_text(encoding="utf-8")
TOGGLE = "MIXIE_CHAT_OT_toggle_completion_sound"
OFF, CHIME, BELL = "OFF", "CHIME", "BELL"
WIDTHS = (1.8, 6.0)


def _source(module, name, cls=None):
    tree = ast.parse(module)
    scope = tree.body
    if cls:
        scope = next(n for n in scope if isinstance(n, ast.ClassDef) and n.name == cls).body
    node = next(n for n in scope if isinstance(n, ast.FunctionDef) and n.name == name)
    return textwrap.dedent(ast.get_source_segment(module, node))


class WindowManager:
    """The mute BoolProperty: assignment runs the props module's update callback."""

    def __init__(self, ns):
        object.__setattr__(self, "_ns", ns)
        object.__setattr__(self, "mixar_notifications_muted", ns["get_notifications_muted"]())

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)
        if name == "mixar_notifications_muted":
            self._ns["_on_mute_change"](self, None)


def rig(sound, muted, reduce_motion=False):
    config = {"sound": sound, "muted": muted}
    ns = {
        "OFF": OFF, "CHIME": CHIME,
        "get_completion_sound": lambda: config["sound"],
        "set_completion_sound": lambda value: config.__setitem__("sound", value),
        "get_notifications_muted": lambda: config["muted"],
        "set_notifications_muted": lambda value: config.__setitem__("muted", bool(value)),
        "sound_feedback": Mock(),
    }
    for module, name in ((PROPS, "_sync_feedback"), (PROPS, "_on_mute_change"), (OPS, "_sound_off")):
        exec(_source(module, name), ns)
    for name in ("execute", "description"):
        exec(_source(OPS, name, cls=TOGGLE), ns)
    context = NS(window_manager=WindowManager(ns),
                 preferences=NS(view=NS(use_reduce_motion=reduce_motion)))
    return ns, config, ns["sound_feedback"], context


@pytest.mark.parametrize("muted", [True, False])
def test_off_click_selects_chime_unmutes_and_shows_feedback(muted):
    ns, config, feedback, context = rig(OFF, muted)
    assert ns["execute"](None, context) == {'FINISHED'}
    assert config == {"sound": CHIME, "muted": False}
    assert context.window_manager.mixar_notifications_muted is False
    feedback.show.assert_called_once_with(reduce_motion=False)
    feedback.cancel.assert_not_called()


def test_unmuted_click_mutes_keeps_the_clip_and_cancels_feedback():
    ns, config, feedback, context = rig(BELL, False)
    ns["execute"](None, context)
    assert config == {"sound": BELL, "muted": True}
    feedback.cancel.assert_called_once_with()
    feedback.show.assert_not_called()


def test_muted_click_unmutes_keeps_the_clip_and_shows_feedback():
    ns, config, feedback, context = rig(BELL, True, reduce_motion=True)
    ns["execute"](None, context)
    assert config == {"sound": BELL, "muted": False}
    feedback.show.assert_called_once_with(reduce_motion=True)
    # Unmuting is not a silencing change: the update redraws, it never cancels.
    feedback.cancel.assert_not_called()
    feedback.redraw.assert_called_once_with()


@pytest.mark.parametrize("sound, muted, off", [
    (OFF, False, True), (BELL, True, True), (BELL, False, False), (CHIME, False, False),
])
def test_description_follows_the_resolved_state(sound, muted, off):
    ns, _config, _feedback, context = rig(sound, muted)
    text = ns["description"](None, context, None)
    assert text.endswith("click to enable" if off else "click to mute")


def test_toggle_and_topbar_never_read_the_enum_mirror():
    # The enum getter maps against an items cache that can miss a catalog clip.
    for module in (OPS, TOPBAR):
        assert "mixar_completion_sound" not in module
    assert "'OFF'" not in TOPBAR and "OFF" in TOPBAR
    # The operator owns the confirmation: no cancel() precedes show() in execute.
    execute = _source(OPS, "execute", cls=TOGGLE)
    assert "sound_feedback.show(" in execute and "sound_feedback.cancel(" not in execute


def test_preference_sync_cancels_only_when_silencing():
    for sound, muted, cancels in ((OFF, False, True), (BELL, True, True), (BELL, False, False)):
        ns, _config, feedback, _context = rig(sound, muted)
        ns["_sync_feedback"]()
        assert feedback.cancel.called is cancels, (sound, muted)
        assert feedback.redraw.called is not cancels, (sound, muted)


def test_enum_getter_rebuilds_the_items_on_a_cache_miss():
    stale = [(OFF, "Off", ""), (CHIME, "Chime", "")]
    fresh = stale + [(BELL, "Bell", "")]
    rebuilt = Mock(return_value=fresh)
    ns = {"get_completion_sound": lambda: BELL, "_items_cache": stale, "_sound_items": rebuilt}
    for name in ("_index_of", "_sound_get"):
        exec(_source(PROPS, name), ns)
    assert ns["_sound_get"](None) == 2
    rebuilt.assert_called_once()
    ns["get_completion_sound"] = lambda: CHIME
    assert ns["_sound_get"](None) == 1
    rebuilt.assert_called_once()  # A hit never rebuilds.
    ns["get_completion_sound"] = lambda: "GONE"
    assert ns["_sound_get"](None) == 0


class Row:
    def __init__(self):
        self.calls = []

    def row(self, **_kw):
        return self

    def operator(self, idname, **kw):
        self.calls.append((idname, kw))

    def mixar_style(self, **_kw):
        pass


def draw_toggle(sound, muted, fraction, has_operator=True):
    row = Row()
    layout = NS(mixar_surface=lambda **_kw: row)
    ns = {
        "OFF": OFF, "SOUND_FEEDBACK_WIDTHS": WIDTHS,
        "get_completion_sound": lambda: sound,
        "get_notifications_muted": lambda: muted,
        "sound_feedback": NS(expansion=lambda: fraction),
        "bpy": NS(types=NS(MIXIE_CHAT_OT_toggle_completion_sound=object) if has_operator else NS()),
    }
    exec(_source(TOPBAR, "_draw_sound_toggle"), ns)
    context = NS(window_manager=NS(mixar_notifications_muted=muted))
    ns["_draw_sound_toggle"](layout, context)
    return row


def test_topbar_gate_reads_the_resolved_clip_and_mute():
    row = draw_toggle(BELL, False, 0.0)
    (_idname, kw), = row.calls
    assert kw["depress"] is False and kw["icon"] == 'NOTIFICATION_SOUND'
    assert row.ui_units_x == WIDTHS[0]
    for sound, muted in ((BELL, True), (OFF, False)):
        (_idname, kw), = draw_toggle(sound, muted, 1.0).calls
        assert kw["depress"] is False and kw["icon"] == 'NOTIFICATION_SOUND_OFF' and kw["text"] == ''


def test_topbar_label_shows_at_full_expansion_and_hides_without_the_operator():
    row = draw_toggle(BELL, False, 1.0)
    (idname, kw), = row.calls
    assert idname == 'mixie_chat.toggle_completion_sound'
    assert kw["text"] == 'Sound on' and kw["icon"] == 'NONE'
    assert row.ui_units_x == WIDTHS[1] and row.scale_x == 1.0
    assert draw_toggle(BELL, False, 1.0, has_operator=False).calls == []
