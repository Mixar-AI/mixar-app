# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The hosted agent model picker: menu rows, operators, preference mirror.

Python owns the whole picker; C++ on the island draws one pulldown whose label
comes from a WindowManager string and whose click opens this menu. So the
things worth pinning here are the rules the user sees (ineligible greyed not
hidden, BYOK disables every row, an empty catalog fails closed), the request
bytes, and the epoch guard that stops a late response repainting the previous
account's pick in front of the next user.

`bpy` is a MagicMock, so `bpy.types.Menu` is not subclassable — the menu module
is pinned at source/ast level and its DECISIONS live in `core/model_menu.py`,
which is plain Python. Operators are importable (`bpy.types.Operator` is a real
class in the mock) and are driven directly.
"""

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.byok.core import model_menu, model_suggestions, preference_state
from mixar.modules.byok.ui.operators import agent_model_ops
from mixar.modules.common.api.services.agent_service import AgentService

PICKER_SOURCE = SCRIPTS / "mixar" / "modules" / "byok" / "core" / "picker.py"
MIRROR_SOURCE = SCRIPTS / "mixar" / "modules" / "byok" / "core" / "picker_mirror.py"
PICK_OPS_SOURCE = SCRIPTS / "mixar" / "modules" / "byok" / "ui" / "operators" / "agent_pick_ops.py"
ISLAND = ROOT / "src" / "source" / "blender" / "editors" / "space_agent_bubble"
PROPS_SOURCE = (
    SCRIPTS / "mixar" / "modules" / "byok" / "ui" / "properties" / "agent_model_props.py"
)
AUTH_OPS_SOURCE = (
    SCRIPTS / "mixar" / "modules" / "space_mixie_chat" / "ui" / "operators" / "auth_ops.py"
)

#: The names the C++ footer button and island chip read. Changing one silently
#: blanks a control on both surfaces.
WM_PROPS = (
    "mixar_agent_model_provider",
    "mixar_agent_model_id",
    "mixar_agent_model_label",
    "mixar_agent_model_thinking",
    "mixar_agent_model_byok_active",
    "mixar_agent_model_eligible",
)

PICK_OP = "MIXAR_OT_agent_pick"


def _record(model_id, **overrides):
    row = {
        "provider_id": "anthropic",
        "provider_label": "Anthropic",
        "model_id": model_id,
        "model_label": model_id,
        "platform_available": True,
        "byok_available": True,
        "supports_vision": True,
        "min_tier": "",
        "eligible": True,
        "thinking_levels": [],
    }
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def clean_state():
    preference_state.clear()
    model_suggestions.clear()
    yield
    preference_state.clear()
    model_suggestions.clear()


def _kinds(rows):
    return [row.kind for row in rows]


# ---------------------------------------------------------------------------
# Menu rows
# ---------------------------------------------------------------------------























# ---------------------------------------------------------------------------
# Menu module (source-level: bpy.types.Menu is not subclassable under the mock)
# ---------------------------------------------------------------------------

def test_the_island_chip_opens_the_hand_drawn_model_card():
    """The chip is one operator button over the whole chip; the card is drawn
    by hand over the island window by a modal operator (no Blender popup, no
    stock or Cinema widgets, no free `wm.call_menu`)."""
    provider = (ISLAND / "agent_ui_provider.cc").read_text(encoding="utf-8")
    assert '"MIXAR_OT_agent_model_card"' in provider
    assert "agent_model_card_anchor(" in provider
    assert "uiDefMenuBut(" not in provider and "wm.call_menu" not in provider
    card = (ISLAND / "agent_ui_model_card.cc").read_text(encoding="utf-8")
    assert "WM_draw_cb_activate(win, draw, state)" in card
    assert "WM_event_add_modal_handler(C, op)" in card
    draw = (ISLAND / "agent_ui_model_card_draw.cc").read_text(encoding="utf-8")
    assert "UI_mixar_cinema_row_tag" not in draw and "uiDef" not in draw


def test_every_pick_runs_the_one_pick_operator():
    data = (ISLAND / "agent_ui_model_card_data.cc").read_text(encoding="utf-8")
    card = (ISLAND / "agent_ui_model_card.cc").read_text(encoding="utf-8")
    assert f'PICK_OP = "{PICK_OP}"' in card and f'PICK_OP = "{PICK_OP}"' in data
    ops = PICK_OPS_SOURCE.read_text(encoding="utf-8")
    assert 'bl_idname = "mixar.agent_pick"' in ops
    for prop in ("source", "provider", "model", "thinking"):
        assert f'"{prop}"' in card
        assert f"    {prop}: " in ops


def test_a_click_away_reaches_what_it_was_on():
    """FINISHED | PASS and RUNNING_MODAL | PASS both count as handled at the
    window level, so the regions under the card never saw the event."""
    card = (ISLAND / "agent_ui_model_card.cc").read_text(encoding="utf-8")
    assert "constexpr wmOperatorStatus PASS = OPERATOR_PASS_THROUGH;" in card
    assert "wmOperatorStatus(OPERATOR_CANCELLED |" in card


def test_the_pick_operator_is_auto_registered_through_a_classes_tuple():
    tree = ast.parse(PICK_OPS_SOURCE.read_text(encoding="utf-8"))
    assigned = {
        target.id
        for node in tree.body if isinstance(node, ast.Assign)
        for target in node.targets if isinstance(target, ast.Name)
    }
    assert "classes" in assigned
    assert not [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in {"register", "unregister"}
    ]


def test_the_picker_never_hardcodes_a_model_list():
    assert "get_platform_models()" in MIRROR_SOURCE.read_text(encoding="utf-8")
    for path in (PICKER_SOURCE, MIRROR_SOURCE, PICK_OPS_SOURCE):
        source = path.read_text(encoding="utf-8").lower()
        for vendor in ("claude", "gpt-", "gemini", "anthropic", "openai"):
            assert vendor not in source, (path.name, vendor)


def test_the_picker_does_not_surface_supports_vision():
    """An explicit product decision: no "text-only" note anywhere in the picker."""
    for path in (PICKER_SOURCE, MIRROR_SOURCE, PROPS_SOURCE, ISLAND / "agent_ui_model_card.cc",
                 ISLAND / "agent_ui_model_card_data.cc", ISLAND / "agent_ui_model_card_draw.cc"):
        assert "supports_vision" not in path.read_text(encoding="utf-8")
    assert "supports_vision" not in (
        SCRIPTS / "mixar" / "modules" / "byok" / "core" / "model_menu.py"
    ).read_text(encoding="utf-8")


def test_the_wm_mirror_registers_exactly_the_contracted_property_names():
    source = PROPS_SOURCE.read_text(encoding="utf-8")
    for name in WM_PROPS:
        assert f"WM.{name} = " in source




def test_the_footer_invokes_the_dialog_not_executes_it():
    """The BYOK dialog operator does all its work in invoke() — execute() is a
    deliberate no-op ("clicking does nothing" was a real report). The card's
    footer calls it with InvokeDefault, after closing itself."""
    card = (ISLAND / "agent_ui_model_card.cc").read_text(encoding="utf-8")
    assert 'SETTINGS_OP = "MIXAR_BYOK_OT_open_dialog"' in card
    footer = card[card.index("wmOperatorStatus run_footer("):]
    footer = footer[:footer.index("\n}\n")]
    assert footer.index("teardown(C, op)") < footer.index("WM_operator_name_call(")
    assert "wm::OpCallContext::InvokeDefault" in footer


def test_the_dialog_opens_in_the_main_window_not_the_island():
    """The only entry point since PR #1562 is the picker menu in the Agent
    Bubble island (~460px tall). A props dialog opened THERE is clipped to a
    scrolling sliver over the composer. The operator must re-target the main
    window — and override the WINDOW only: the bubble's screen is a temporary
    one and `temp_override(screen=...)` raises "Overriding context with an
    active temporary screen isn't supported", which silently opened nothing."""
    from pathlib import Path
    src = Path("src/scripts/mixar/modules/byok/ui/operators/byok_ops.py").read_text()
    assert "_dialog_host_window(context)" in src
    assert "context.temp_override(window=host)" in src
    assert "temp_override(window=host, screen=" not in src
    assert "is_agent_bubble_window" in src


def test_unfolding_thinking_brings_its_levels_into_view():
    """Unfolding the current pick's "Thinking" on the last visible row used to
    leave Low / High below the fold (QA 2026-10-17, F7): the unfold scrolled
    the disclosure into view only. It now reveals the last level, then keeps
    the disclosure itself visible when both do not fit."""
    card = (ISLAND / "agent_ui_model_card.cc").read_text(encoding="utf-8")
    unfold = card[card.index("state->thinking_open = !state->thinking_open;"):]
    unfold = unfold[:unfold.index("else if (pickable(")]
    assert "reveal_levels(*state," in unfold
    layout = (ISLAND / "agent_ui_model_card_layout.cc").read_text(encoding="utf-8")
    body = layout[layout.index("void reveal_levels(State &state, const int line)"):]
    body = body[:body.index("\n}\n")]
    assert "LineKind::Level" in body
    assert body.index("scroll_into_view(state, last);") < body.index("scroll_into_view(state, line);")
