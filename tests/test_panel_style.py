# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the shared ``common.utils.panel_style`` new-design helpers.

Two layers:

1. Behavioural — drive every primitive with a fake ``uiLayout`` that either
   exposes the native ``mixar_*`` methods (a modern build) or does not (an
   older build / the ``bpy`` test mock), and assert each primitive dispatches
   to the styled widget when present and degrades to ``box()`` / ``prop()`` /
   ``operator()`` otherwise.

2. Source-level — the migrated panels subclass ``bpy.types.Panel``, which is a
   ``MagicMock`` under the test stub, so their ``draw()`` cannot be invoked
   directly (the class itself becomes a mock). Following the repo convention
   (see other ``tests/`` AST/source checks), assert at the source level that
   the panels adopt the shared helper and drop their bare ``box()`` sections.
"""

import types
from pathlib import Path

from mixar.modules.common.utils import panel_style

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src/scripts/mixar/modules"


# ---------------------------------------------------------------------------
# Fake uiLayout
# ---------------------------------------------------------------------------

class PlainLayout:
    """A minimal ``uiLayout`` with only the stock API — no ``mixar_*``."""

    def __init__(self, rec=None):
        self.rec = rec if rec is not None else []
        # Freely-settable layout attributes the panels touch.
        self.alert = False
        self.enabled = True
        self.scale_x = 1.0
        self.scale_y = 1.0

    def _mk(self):
        # Children keep the same type, so styled-ness propagates down.
        return type(self)(self.rec)

    def column(self, *a, **k):
        self.rec.append("column")
        return self._mk()

    def row(self, *a, **k):
        self.rec.append("row")
        return self._mk()

    def box(self, *a, **k):
        self.rec.append("box")
        return self._mk()

    def label(self, *a, **k):
        self.rec.append("label")

    def separator(self, *a, **k):
        self.rec.append("separator")

    def prop(self, *a, **k):
        self.rec.append("prop")

    def operator(self, *a, **k):
        self.rec.append("operator")
        return types.SimpleNamespace()


class StyledLayout(PlainLayout):
    """A ``uiLayout`` from a build that ships the ``mixar_*`` widgets."""

    def mixar_section(self):
        self.rec.append("mixar_section")
        return self._mk()

    def mixar_dropdown(self, *a, **k):
        self.rec.append("mixar_dropdown")

    def mixar_toggle(self, *a, **k):
        self.rec.append("mixar_toggle")

    def mixar_input(self, *a, **k):
        self.rec.append("mixar_input")

    def mixar_operator(self, *a, **k):
        self.rec.append("mixar_operator")
        return types.SimpleNamespace()


_DATA = types.SimpleNamespace(some_enum="A", some_bool=True, some_text="hi")


# ---------------------------------------------------------------------------
# section()
# ---------------------------------------------------------------------------

def test_section_falls_back_to_box_without_styled_widgets():
    layout = PlainLayout()
    col = panel_style.section(layout)
    assert "box" in layout.rec
    assert "mixar_section" not in layout.rec
    assert isinstance(col, PlainLayout)


def test_section_uses_mixar_section_when_available():
    layout = StyledLayout()
    panel_style.section(layout)
    assert "mixar_section" in layout.rec
    assert "box" not in layout.rec


def test_section_label_draws_header_and_separator():
    layout = StyledLayout()
    col = panel_style.section(layout, label="Channels", icon="NODE_COMPOSITING")
    # Header label + intra separator drawn into the returned column.
    assert "label" in col.rec
    assert "separator" in col.rec


# ---------------------------------------------------------------------------
# dropdown() / toggle() / text_input()
# ---------------------------------------------------------------------------

def test_dropdown_dispatch():
    styled = StyledLayout()
    panel_style.dropdown(styled, _DATA, "some_enum", text="Model")
    assert styled.rec == ["mixar_dropdown"]

    plain = PlainLayout()
    panel_style.dropdown(plain, _DATA, "some_enum", text="Model")
    assert plain.rec == ["prop"]


def test_toggle_dispatch():
    styled = StyledLayout()
    panel_style.toggle(styled, _DATA, "some_bool", text="PBR")
    assert styled.rec == ["mixar_toggle"]

    plain = PlainLayout()
    panel_style.toggle(plain, _DATA, "some_bool", text="PBR")
    assert plain.rec == ["prop"]


def test_text_input_dispatch():
    styled = StyledLayout()
    panel_style.text_input(styled, _DATA, "some_text", text="Prompt")
    assert styled.rec == ["mixar_input"]

    plain = PlainLayout()
    panel_style.text_input(plain, _DATA, "some_text", text="Prompt")
    assert plain.rec == ["prop"]


# ---------------------------------------------------------------------------
# primary_operator()
# ---------------------------------------------------------------------------

def test_primary_operator_uses_mixar_operator_and_returns_props():
    styled = StyledLayout()
    op = panel_style.primary_operator(styled, "mixie_chat.login", text="Login")
    assert styled.rec == ["mixar_operator"]
    assert op is not None  # returned so callers can set operator fields


def test_primary_operator_falls_back_to_operator():
    plain = PlainLayout()
    op = panel_style.primary_operator(plain, "mixie_chat.login", text="Login")
    assert plain.rec == ["operator"]
    assert op is not None


# ---------------------------------------------------------------------------
# hint() / section_separator()
# ---------------------------------------------------------------------------

def test_hint_is_a_scaled_down_label():
    layout = PlainLayout()
    panel_style.hint(layout, "Max 6MB", icon="INFO")
    assert "row" in layout.rec  # hint draws into its own row


def test_section_separator_uses_section_spacing():
    layout = PlainLayout()
    panel_style.section_separator(layout)
    assert "separator" in layout.rec


def test_spacing_tokens_match_moodboard_rhythm():
    # The common helper deliberately mirrors moodboard's spacing constants so
    # every Mixar surface shares one rhythm; keep them in lock-step.
    from mixar.modules.moodboard import constants as mb
    assert panel_style.SEP_SECTION == mb.SEP_SECTION
    assert panel_style.SEP_INTRA == mb.SEP_INTRA
    assert panel_style.SEP_FOOTER == mb.SEP_FOOTER
    assert panel_style.HINT_SCALE_Y == mb.HINT_SCALE_Y


# ---------------------------------------------------------------------------
# Source-level: migrated panels adopt the shared helper
# ---------------------------------------------------------------------------

def test_login_panel_uses_new_design_helper():
    src = (SRC / "space_mixie_chat/ui/login_panel.py").read_text()
    assert "from mixar.modules.common.utils import panel_style" in src
    assert "panel_style.section(" in src
    assert "panel_style.primary_operator(" in src
    # The bare box() error/expired cards were replaced by styled sections.
    assert "col.box()" not in src


def test_texture_sets_panel_uses_new_design_helper():
    src = (SRC / "space_texture_sets/ui/panels.py").read_text()
    assert "from ...common.utils import panel_style" in src
    assert "panel_style.section(" in src
    # Both legacy section boxes were migrated.
    assert "layout.box()" not in src
    assert "col.box()" not in src


# ---------------------------------------------------------------------------
# Behavioural: run the REAL login draw code through both layouts
# ---------------------------------------------------------------------------

def _import_login_draw():
    """Import the login module's callable draw fn under bpy stubs."""
    import sys
    from unittest.mock import MagicMock
    for n in ('bpy', 'bpy.types', 'bpy.props', 'bpy.utils', 'bpy.app',
              'bpy.app.handlers', 'bpy.app.timers', 'bpy.context',
              'bpy.data', 'bpy.ops', 'bpy.ops.mixar'):
        sys.modules.setdefault(n, MagicMock(name=n))
    sys.modules['bpy.app.handlers'].persistent = lambda f: f
    from mixar.modules.space_mixie_chat.ui.login_panel import draw_login
    return draw_login


def _wm(expired=False, error="", logging_in=False):
    return types.SimpleNamespace(
        mixie_chat_session_expired=expired,
        mixie_chat_login_error=error,
        mixie_chat_is_logging_in=logging_in,
    )


def test_login_draw_styled_uses_new_design_widgets():
    draw_login = _import_login_draw()
    layout = StyledLayout()
    draw_login(layout, _wm())
    # Login CTA renders through the gradient mixar_operator, not a plain one.
    assert "mixar_operator" in layout.rec
    assert "operator" not in layout.rec


def test_login_draw_error_branch_uses_styled_section():
    draw_login = _import_login_draw()
    layout = StyledLayout()
    draw_login(layout, _wm(error="Network unreachable while contacting server"))
    assert "mixar_section" in layout.rec
    assert "mixar_operator" in layout.rec


def test_login_draw_falls_back_cleanly_without_styled_widgets():
    draw_login = _import_login_draw()
    layout = PlainLayout()
    # All three branches must run without error on an older build.
    draw_login(layout, _wm(expired=True))
    draw_login(layout, _wm(error="boom"))
    draw_login(layout, _wm(logging_in=True))
    assert "box" in layout.rec       # sections degrade to box()
    assert "operator" in layout.rec  # CTA degrades to operator()
    assert "mixar_operator" not in layout.rec
