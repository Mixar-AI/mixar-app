# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Pins the "opening press's release" guard in the interface overlays.

Blender 5.3 (upstream f2134b772e3) places a mouse-positioned dialog with its
default button under the cursor. Mixar's native surfaces open dialogs from a
left-button PRESS (the Scenes drawer's delete controls), so the release of
that same press landed on the default button and answered the dialog: with a
"No" default the delete confirmation closed the moment it appeared.

- `interface.cc` `block_bounds_calc_popup` flags the popup's handle when it
  places the default button under the cursor while the window's last button
  event is a left press, on first creation only;
- `interface_handlers.cc` swallows the one release for a flagged popup before
  the upstream "release over a highlighted popup button applies it" branch,
  and a press on a popup button clears the flag;
- the flag lives on `PopupBlockHandle` (`interface_intern.hh`), which survives
  popup refreshes.

The running-app proof is the harness's Scenes drawer delete replays (TAB-01,
TAB-04..07, TAB-10)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTERFACE = ROOT / "src" / "source" / "blender" / "editors" / "interface"
FLAG = "mixar_swallow_open_release"


def _text(name: str) -> str:
    return (INTERFACE / name).read_text(encoding="utf-8")


def _function(text: str, signature: str) -> str:
    start = text.index(signature)
    return text[start:text.index("\n}\n", start)]


def test_the_flag_lives_on_the_popup_handle_and_defaults_off():
    intern = _text("interface_intern.hh")
    handle = intern[intern.index("struct PopupBlockHandle {"):]
    handle = handle[:handle.index("\n};\n")]
    assert f"bool {FLAG} = false;" in handle


def test_placement_flags_only_a_first_creation_under_a_held_left_button():
    body = _function(_text("interface.cc"), "static void block_bounds_calc_popup(")
    default_button = body.index("block_active_default_button_find(block)")
    flagged = body.index(f"block->handle->{FLAG} = true;")
    assert default_button < flagged < body.index("block_bounds_calc(block);")
    condition = body[default_button:flagged]
    assert "!block->handle->refresh" in condition
    assert "event_state->type == LEFTMOUSE" in condition
    assert "event_state->val == KM_PRESS" in condition
    # The event state is null while a popup refreshes (debug builds): never read it unchecked.
    assert "block->handle && " in condition and " event_state &&" in condition
    assert body.count(f"{FLAG} = true;") == 1


def test_the_handler_swallows_one_release_before_upstream_applies_it():
    handlers = _text("interface_handlers.cc")
    assert handlers.count(f"->{FLAG} = false;") == 2 and f"{FLAG} = true" not in handlers
    swallow = handlers.index(f"but->block->handle->{FLAG})\n    {{\n      but->block->handle->{FLAG} = false;\n      return WM_UI_HANDLER_BREAK;")
    upstream_release = handlers.index(
        "if (event->type == LEFTMOUSE && event->val == KM_RELEASE && but->block->handle) {\n"
        "      /* regular buttons will be 'UI_SELECT', menu items 'UI_HOVER' */"
    )
    assert swallow < upstream_release
    assert "event->val == KM_RELEASE && but->block->handle &&" in handlers[swallow - 120:swallow]


def test_a_press_on_a_popup_button_ends_the_wait():
    handlers = _text("interface_handlers.cc")
    press = handlers.index(
        "if (but->block->handle) {\n"
        f"        but->block->handle->{FLAG} = false;\n"
        "      }\n"
        "      button_activate_state(C, but, BUTTON_STATE_WAIT_RELEASE);"
    )
    assert "event->type == LEFTMOUSE && event->val == KM_PRESS" in handlers[press - 200:press]
