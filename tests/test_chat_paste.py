# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ctrl/Cmd+V must paste into the chat composer, focus or no focus.

Text paste used to work through exactly one path: the inline hook in
``interface_handlers.cc``, which only runs while the composer holds
text-edit focus. The keymap chord behind it — the path taken whenever it
does NOT hold focus — was bound to ``mixie_chat.paste_image``, which
returns ``CANCELLED`` for a clipboard carrying no image. So a text paste
made while the composer was unfocused did nothing at all, silently.

That is the normal state after any focus change: ``WINDEACTIVATE`` exits
text editing and nothing re-activates the button. It is also the state an
external dictation tool leaves behind — it puts its transcript on the
clipboard and injects the paste chord, and by then the composer is out of
edit mode. In the Agent Bubble, whose window hides on app deactivation,
this was the only outcome there was.

Pinned here: the unified operator exists and is registered, every plain
paste chord routes to it, the image-only operator keeps the ``CANCELLED``
contract the inline C++ hook depends on, and the chord still matches when
an extra Ctrl/Cmd is held (dictation tools inject the chord with their own
push-to-talk modifier still down).
"""

import ast
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.space_mixie_chat.ui.operators import clipboard_ops  # noqa: E402

CPP = ROOT / "src" / "source" / "blender" / "editors"
KEYMAP_PY = SCRIPTS / "mixar" / "modules" / "space_mixie_chat" / "ui" / "keymap.py"
HANDLERS_CC = CPP / "interface" / "interface_handlers.cc"
CHAT_CC = CPP / "space_mixie_chat" / "space_mixie_chat.cc"
BUBBLE_CC = CPP / "space_agent_bubble" / "space_agent_bubble.cc"


def _fake_context(clipboard, current_input=""):
    scene = SimpleNamespace(mixie_chat_input=current_input)
    return SimpleNamespace(
        scene=scene,
        window_manager=SimpleNamespace(clipboard=clipboard),
    )


class TestUnifiedPasteOperator:
    """``mixie_chat.paste`` is the operator the keymaps bind."""

    def test_operator_exists_and_is_registered(self):
        op = clipboard_ops.MIXIE_CHAT_OT_paste
        assert op.bl_idname == "mixie_chat.paste"
        assert op in clipboard_ops.classes

    def test_image_operator_keeps_its_image_only_contract(self):
        """The inline C++ hook falls back on CANCELLED — do not break it."""
        source = HANDLERS_CC.read_text(encoding="utf-8")
        assert '"MIXIE_CHAT_OT_paste_image"' in source, (
            "the inline text-edit hook must keep calling the image-only "
            "operator, so a no-image clipboard falls through to "
            "ui_textedit_copypaste and lands at the caret"
        )
        image_op = clipboard_ops.MIXIE_CHAT_OT_paste_image
        assert image_op.bl_idname == "mixie_chat.paste_image"


class TestClipboardTextAppend:
    """The text half of the paste, exercised directly."""

    def test_appends_clipboard_to_existing_input(self, monkeypatch):
        monkeypatch.setattr(clipboard_ops, "redraw_chat_areas", lambda: None)
        ctx = _fake_context("world", current_input="hello ")
        assert clipboard_ops.append_clipboard_text_to_input(ctx) is True
        assert ctx.scene.mixie_chat_input == "hello world"

    def test_empty_clipboard_inserts_nothing(self, monkeypatch):
        monkeypatch.setattr(clipboard_ops, "redraw_chat_areas", lambda: None)
        ctx = _fake_context("", current_input="kept")
        assert clipboard_ops.append_clipboard_text_to_input(ctx) is False
        assert ctx.scene.mixie_chat_input == "kept"

    def test_clamps_to_max_message_length(self, monkeypatch):
        monkeypatch.setattr(clipboard_ops, "redraw_chat_areas", lambda: None)
        limit = clipboard_ops.MAX_MESSAGE_LENGTH
        reports = []
        ctx = _fake_context("x" * (limit + 50))
        assert clipboard_ops.append_clipboard_text_to_input(
            ctx, lambda kind, msg: reports.append((kind, msg))
        ) is True
        assert len(ctx.scene.mixie_chat_input) == limit
        assert reports and 'WARNING' in reports[0][0]

    def test_submit_marker_is_stripped(self):
        """A clipboard carrying \\x1F would otherwise send the message."""
        assert clipboard_ops.SUBMIT_MARKER == "\x1F"
        out = clipboard_ops.normalize_pasted_text("send me\x1F")
        assert "\x1F" not in out
        assert out == "send me"

    def test_crlf_is_normalised(self):
        assert clipboard_ops.normalize_pasted_text("a\r\nb\rc") == "a\nb\nc"

    def test_none_and_empty_are_safe(self):
        assert clipboard_ops.normalize_pasted_text(None) == ""
        assert clipboard_ops.normalize_pasted_text("") == ""


class TestPlainChordRoutesToUnifiedOperator:
    """Every registration of the plain paste chord, in both languages."""

    def test_addon_keyconfig_binds_plain_paste(self):
        source = KEYMAP_PY.read_text(encoding="utf-8")
        assert "'mixie_chat.paste'" in source, (
            "the plain chord must be registered in the ADDON keyconfig — "
            "the GUI keyconfig preset reload wipes C-registered items"
        )

    def test_addon_keyconfig_tolerates_a_held_extra_modifier(self):
        """Dictation tools inject the chord with their trigger key down."""
        tree = ast.parse(KEYMAP_PY.read_text(encoding="utf-8"))
        modifier_sets = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
            if keys and keys <= {"ctrl", "oskey", "shift", "alt"}:
                modifier_sets.append(keys)
        assert {"ctrl", "oskey"} in modifier_sets, (
            "expected a ctrl+oskey paste variant so an injected chord still "
            "matches while the tool's own push-to-talk modifier is held"
        )

    def test_c_keymaps_bind_the_unified_operator(self):
        for path in (CHAT_CC, BUBBLE_CC):
            source = path.read_text(encoding="utf-8")
            assert '"MIXIE_CHAT_OT_paste"' in source, (
                f"{path.name} must bind the plain chord to the unified "
                "paste operator, not the image-only one"
            )
            assert '"MIXIE_CHAT_OT_paste_image", &paste_params' not in source, (
                f"{path.name} still binds a paste chord to the image-only "
                "operator; a text paste reaching it is dropped silently"
            )


class TestInlineModifierGate:
    """The in-field chord must survive an extra held modifier too."""

    def test_chat_spaces_use_the_relaxed_gate(self):
        source = HANDLERS_CC.read_text(encoding="utf-8")
        assert "ui_textedit_clipboard_modifier_match" in source
        # Stock exact-match behaviour is kept for every other text field.
        assert "return event->modifier == KM_CTRL;" in source
        assert "return ELEM(event->modifier, KM_OSKEY, KM_CTRL);" in source
        # ... and Shift stays out of it, so Ctrl/Cmd+Shift+V remains the
        # explicit paste-image chord rather than being eaten as text paste.
        assert "(event->modifier & (KM_SHIFT | KM_ALT)) == 0" in source
