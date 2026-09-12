# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Which Mixar surfaces become glass panes, and which stay flat.

The kit (`tests/test_mixar_liquid_glass_kit.py`) pins the material and the
painter. This file pins the CONVERSION: every surface that should adopt the
material, every control that must not, and the single seam that keeps the two
apart.

These source contracts complement the native build and GUI replay by pinning
surface adoption and exclusions across the overlay:

* a surface left on the flat fill keeps a raw, hand-mixed dark rectangle that
  no longer matches the family — visible only by comparing two screenshots;
* a control converted to a pane bleeds the sheet under it, and a slider track
  that shows the card through it stops reading as a groove;
* a seam that re-implements the material instead of delegating lets one
  surface drift out of the family and stops a palette edit from reaching it;
* a seam that takes a colour lets each call site pick its own tint, which is
  the drift the role table exists to prevent;
* a sweep that keeps no register of what it has covered lets a later pass
  convert a surface twice or miss one, and neither shows up until two builds
  are compared by eye.

Run with the repo venv: ``python -m pytest -q`` from the repository root.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ED = ROOT / "src" / "source" / "blender" / "editors"
IFACE = ED / "interface"

CARD_PAINT_PATH = IFACE / "interface_mixar_card_paint.hh"
CARD_PAINT = CARD_PAINT_PATH.read_text(encoding="utf-8")
CARD_BUTTON_PATH = IFACE / "interface_mixar_card_button.cc"
CARD_BUTTON = CARD_BUTTON_PATH.read_text(encoding="utf-8")
PROFILE_DRAW_PATH = IFACE / "interface_mixar_profile_card_draw.cc"
PROFILE_DRAW = PROFILE_DRAW_PATH.read_text(encoding="utf-8")
TOPBAR_PATH = IFACE / "interface_mixar_topbar.cc"
TOPBAR = TOPBAR_PATH.read_text(encoding="utf-8")
CINEMA_ROW_PATH = IFACE / "interface_mixar_cinema_row.cc"
CINEMA_ROW = CINEMA_ROW_PATH.read_text(encoding="utf-8")
CINEMA_VALUE_PATH = IFACE / "interface_mixar_cinema_row_value.cc"
CINEMA_VALUE = CINEMA_VALUE_PATH.read_text(encoding="utf-8")
SECTION_PATH = IFACE / "interface_mixar_section.cc"
SECTION = SECTION_PATH.read_text(encoding="utf-8")
WIDGETS_PATH = IFACE / "interface_widgets.cc"
WIDGETS = WIDGETS_PATH.read_text(encoding="utf-8")
CHAT = ED / "space_mixie_chat"
CHAT_INTERN = (CHAT / "mixie_chat_intern.hh").read_text(encoding="utf-8")
CHAT_PRIMITIVES = (CHAT / "mixie_chat_ui_primitives.cc").read_text(encoding="utf-8")
CHAT_WIDGETS = (CHAT / "mixie_chat_ui_widgets.cc").read_text(encoding="utf-8")
CHAT_CONTENT = (CHAT / "mixie_chat_messages_content.cc").read_text(encoding="utf-8")
CHAT_RENDER = (CHAT / "mixie_chat_messages_render.cc").read_text(encoding="utf-8")
AGENT = ED / "space_agent_bubble"
AGENT_THEME = (AGENT / "agent_ui_theme.hh").read_text(encoding="utf-8")
AGENT_LAYOUT_HH = (AGENT / "agent_ui_layout.hh").read_text(encoding="utf-8")
AGENT_LAYOUT = (AGENT / "agent_ui_layout.cc").read_text(encoding="utf-8")
AGENT_DRAW = (AGENT / "agent_ui_draw.cc").read_text(encoding="utf-8")


def _fn_body(src: str, signature: str) -> str:
    """The braced body of the first function whose text starts with
    ``signature``."""
    start = src.index(signature)
    brace = src.index("{", start)
    depth = 0
    for i in range(brace, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[brace : i + 1]
    raise AssertionError(f"unbalanced braces after {signature!r}")


def _code(src: str) -> str:
    """A file with its comments removed, so prose cannot satisfy a contract."""
    without_blocks = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", without_blocks)


def _overlay_sources() -> dict[str, str]:
    """The overlay's editors tree, comment-stripped, by path relative to ``ED``.

    ``src/`` holds only the files the overlay adds or replaces, so this is
    every surface that can reach the painter — not the whole of Blender. The
    comments go because the register below is about what the code does, and
    the sweep's own prose names roles it has already painted.
    """
    return {
        path.relative_to(ED).as_posix(): _code(path.read_text(encoding="utf-8"))
        for path in sorted(ED.rglob("*"))
        if path.suffix in {".cc", ".hh"}
    }


SOURCES = _overlay_sources()

# The five ways a surface asks the family for a pane: the seam every Mixar
# surface crosses, the painter itself, and the three per-tree wrappers whose
# call sites live outside `blender::ui`.
PANE_ENTRY_POINTS = (
    "mixar_card_glass_round(",
    "mixar_glass_draw(",
    "moodboard_draw_glass_pane(",
    "glass_fill_round(",
    "glass_pane(",
)

# The register: every file that reaches the painter, and the role literals it
# hands over. The painter draws the role it is given, so it names none. A
# conversion lands its file here in the same commit.
PANE_CALLS = {
    "interface/interface_mixar_liquid_glass_draw.cc": (),
    "interface/interface_mixar_topbar.cc": ("MIXAR_GLASS_PILL",),
    "interface/interface_mixar_zen_chrome.cc": ("MIXAR_GLASS_ISLAND",),
    "space_view3d/view3d_director_cinema_paint.cc": ("MIXAR_GLASS_CARD",),
    "interface/interface_mixar_card_button.cc": ("MIXAR_GLASS_CHIP",),
    "interface/interface_mixar_profile_card_draw.cc": ("MIXAR_GLASS_CHIP",),
    "interface/interface_mixar_cinema_row.cc": ("MIXAR_GLASS_CHIP",),
    "interface/interface_mixar_section.cc": ("MIXAR_GLASS_CHIP",),
    "interface/interface_widgets.cc": ("MIXAR_GLASS_CHIP",),
    "space_agent_bubble/agent_ui_draw.cc": ("MIXAR_GLASS_PILL",),
    "space_view3d/view3d_agent_panel_draw.cc": ("MIXAR_GLASS_PANEL",),
    "space_mixie/mixie_draw_moodboard.cc": ("MIXAR_GLASS_MOODBOARD",),
    "space_mixie/mixie_draw_moodboard_graph.cc": (),
    "space_mixie/mixie_draw_moodboard_node_ui.cc": (),
    "space_mixie_chat/mixie_chat_ui_primitives.cc": ("MIXAR_GLASS_CHAT",),
    "space_mixie_chat/mixie_chat_ui_widgets.cc": (),
    "space_mixie_chat/mixie_chat_messages_content.cc": (),
}

# The family declares eight roles; seven have a surface. MENU is the queue.
UNPAINTED_ROLES = (
    "MIXAR_GLASS_MENU",
)

# The kit: the header that enumerates the roles, the table that gives each a
# row, the painter, the backdrop chain and the seam. A role with no surface
# may live here and nowhere else.
KIT_FILES = {
    "include/ED_mixar_glass.hh",
    "interface/interface_mixar_card_paint.hh",
    "interface/interface_mixar_liquid_glass.cc",
    "interface/interface_mixar_liquid_glass_draw.cc",
    "interface/interface_mixar_liquid_glass_tokens.cc",
}


