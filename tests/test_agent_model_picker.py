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

MENU_SOURCE = (
    SCRIPTS / "mixar" / "modules" / "byok" / "ui" / "menus" / "agent_model_menu.py"
)
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

MENU_BL_IDNAME = "MIXIE_CHAT_MT_agent_model"


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

def test_rows_show_only_model_names_and_keep_provider_identity():
    rows = model_menu.build_rows([
        _record("claude-sonnet-4-6", model_label="Claude Sonnet 4.6"),
    ])

    assert rows[0].kind == "MODEL"
    assert rows[0].label == "Claude Sonnet 4.6"
    assert rows[0].provider == "anthropic"
    # No grouping, no provider header — one row per model, then the tail
    # actions (reset, then the AI Provider Settings route).
    assert _kinds(rows) == ["MODEL", "RESET", "BYOK"]


def test_rows_follow_the_catalog_order_verbatim():
    rows = model_menu.build_rows([
        _record("z-first"), _record("a-second"), _record("m-third"),
    ])

    assert [r.model for r in rows if r.kind == "MODEL"] == [
        "z-first", "a-second", "m-third",
    ]


def test_an_empty_catalog_fails_closed_to_one_disabled_sentinel():
    rows = model_menu.build_rows([])

    assert _kinds(rows) == ["SENTINEL", "BYOK"]
    assert rows[0].kind == "SENTINEL"
    assert rows[0].enabled is False
    # Never a hardcoded model list, and no clickable reset on a dead menu.
    assert rows[0].provider == "" and rows[0].model == ""
    # The key route survives an empty catalog on purpose: nothing hosted to
    # pick is exactly when a user's own key is the way forward.
    assert rows[1].kind == "BYOK" and rows[1].enabled is True


def test_an_ineligible_row_is_greyed_not_hidden():
    rows = model_menu.build_rows([
        _record("allowed"),
        _record("locked", eligible=False, min_tier="studio"),
    ])

    models = [row for row in rows if row.kind == "MODEL"]
    assert [row.model for row in models] == ["allowed", "locked"]
    assert models[0].enabled is True
    assert models[1].enabled is False


def test_byok_active_disables_every_row():
    rows = model_menu.build_rows(
        [_record("a"), _record("b", thinking_levels=["high"])],
        byok_active=True,
    )

    assert any(row.kind == "NOTE" for row in rows)
    # Every row EXCEPT the key route, which must stay clickable — it is the
    # way to clear the key without leaving the chat model picker.
    assert all(row.enabled is False for row in rows if row.kind != "BYOK")
    byok = [row for row in rows if row.kind == "BYOK"]
    assert len(byok) == 1 and byok[0].enabled is True


def test_thinking_rows_appear_only_when_the_model_offers_levels():
    rows = model_menu.build_rows([
        _record("plain"),
        _record("thinker", thinking_levels=["low", "high"]),
    ])

    # Levels live in a SUBMENU, never inline: five models x four levels is a
    # 20+ row menu, and Blender column-wraps a menu taller than its window —
    # the levels spilled sideways and were clipped by the island.
    assert _kinds(rows) == ["MODEL", "MODEL", "RESET", "BYOK"]

    # The submenu entry appears only once a model WITH levels is the pick.
    picked = model_menu.build_rows(
        [_record("plain"), _record("thinker", thinking_levels=["low", "high"])],
        active_provider="anthropic", active_model="thinker",
    )
    assert _kinds(picked) == ["MODEL", "MODEL", "THINKING_MENU", "RESET", "BYOK"]

    # ...and not when the pick offers none.
    plain = model_menu.build_rows(
        [_record("plain"), _record("thinker", thinking_levels=["low", "high"])],
        active_provider="anthropic", active_model="plain",
    )
    assert "THINKING_MENU" not in _kinds(plain)


def test_the_thinking_submenu_lists_the_picked_models_levels():
    models = [
        _record("wide", thinking_levels=["low", "medium", "high", "max"]),
        _record("narrow", thinking_levels=["low", "high"]),
    ]

    rows = model_menu.build_thinking_rows(
        models, active_provider="anthropic", active_model="narrow",
        active_thinking="high",
    )
    assert [row.thinking_level for row in rows] == ["low", "high"]
    assert [row.label for row in rows] == ["Thinking: Low", "Thinking: High"]
    assert [row.active for row in rows] == [False, True]
    assert all(row.model == "narrow" for row in rows)

    # Nothing picked, or a model with no levels, means no submenu content.
    assert model_menu.build_thinking_rows(models) == []
    assert model_menu.build_thinking_rows(
        [_record("plain")], active_provider="anthropic", active_model="plain") == []


def test_the_model_row_itself_saves_the_default_thinking_level():
    rows = model_menu.build_rows([_record("thinker", thinking_levels=["high"])])

    assert rows[0].kind == "MODEL"
    assert rows[0].thinking_level == ""


def test_the_active_pick_is_marked_exactly_once():
    models = [
        _record("plain"),
        _record("thinker", thinking_levels=["low", "high"]),
    ]

    # The radio always sits on the MODEL row now — the level is shown in the
    # submenu entry's own label, so marking both would be two marks for one
    # choice.
    rows = model_menu.build_rows(
        models, active_provider="anthropic", active_model="thinker",
        active_thinking="high",
    )
    active = [row for row in rows if row.active]
    assert len(active) == 1
    assert active[0].kind == "MODEL" and active[0].model == "thinker"
    entry = [row for row in rows if row.kind == "THINKING_MENU"]
    assert len(entry) == 1 and entry[0].label == "Thinking: High"

    rows = model_menu.build_rows(
        models, active_provider="anthropic", active_model="plain",
    )
    active = [row for row in rows if row.active]
    assert len(active) == 1
    assert active[0].kind == "MODEL" and active[0].model == "plain"


def test_a_reset_row_closes_a_populated_menu():
    rows = model_menu.build_rows([_record("a")])

    reset = [row for row in rows if row.kind == "RESET"]
    assert len(reset) == 1 and reset[0].enabled is True
    assert reset[0].label == "Mixie" and reset[0].active
    picked = model_menu.build_rows([_record("a")], active_provider="anthropic", active_model="a")
    assert not next(row for row in picked if row.kind == "RESET").active
    byok_rows = model_menu.build_rows([_record("a")], byok_active=True)
    assert [row.enabled for row in byok_rows if row.kind == "RESET"] == [False]


# ---------------------------------------------------------------------------
# Menu module (source-level: bpy.types.Menu is not subclassable under the mock)
# ---------------------------------------------------------------------------

def _menu_tree():
    return ast.parse(MENU_SOURCE.read_text(encoding="utf-8"))


def test_the_island_chip_anchors_the_menu_instead_of_a_free_popup():
    source = (
        ROOT / "src/source/blender/editors/space_agent_bubble/space_agent_bubble.cc"
    ).read_text(encoding="utf-8")
    assert "uiDefMenuBut(" in source
    assert 'WM_menutype_find("MIXIE_CHAT_MT_agent_model"' in source
    assert "wm.call_menu" not in source


def test_the_menu_bl_idname_is_the_contract_the_cpp_button_pops():
    source = MENU_SOURCE.read_text(encoding="utf-8")
    assert f'bl_idname = "{MENU_BL_IDNAME}"' in source

    # The class name IS the bl_idname the island pulldown opens.
    menu_class = next(
        node for node in ast.walk(_menu_tree())
        if isinstance(node, ast.ClassDef) and node.name == MENU_BL_IDNAME
    )
    bases = [base.id for base in menu_class.bases if isinstance(base, ast.Name)]
    assert bases == ["Menu"]


def test_the_menu_is_auto_registered_through_a_classes_tuple():
    tree = _menu_tree()
    assigned = {
        target.id
        for node in tree.body if isinstance(node, ast.Assign)
        for target in node.targets if isinstance(target, ast.Name)
    }
    assert "classes" in assigned
    # Auto-discovery owns registration; a hand-written register() would
    # double-register the menu.
    assert not [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in {"register", "unregister"}
    ]


def test_the_menu_never_hardcodes_a_model_list():
    source = MENU_SOURCE.read_text(encoding="utf-8")
    assert "get_platform_models()" in source
    for vendor in ("claude", "gpt-", "gemini", "anthropic", "openai"):
        assert vendor not in source.lower()


def test_the_menu_does_not_surface_supports_vision():
    """An explicit product decision: no "text-only" note anywhere in the picker."""
    for path in (MENU_SOURCE, PROPS_SOURCE):
        assert "supports_vision" not in path.read_text(encoding="utf-8")
    assert "supports_vision" not in (
        SCRIPTS / "mixar" / "modules" / "byok" / "core" / "model_menu.py"
    ).read_text(encoding="utf-8")


def test_the_wm_mirror_registers_exactly_the_contracted_property_names():
    source = PROPS_SOURCE.read_text(encoding="utf-8")
    for name in WM_PROPS:
        assert f"WM.{name} = " in source


def test_the_key_route_is_always_reachable():
    """Keep the chat's shared settings route reachable in every menu state."""
    states = {
        "populated": model_menu.build_rows([_record("a")]),
        "empty": model_menu.build_rows([]),
        "byok": model_menu.build_rows([_record("a")], byok_active=True),
        "empty_byok": model_menu.build_rows([], byok_active=True),
        "ineligible": model_menu.build_rows([_record("a", eligible=False)]),
    }
    for name, rows in states.items():
        byok = [row for row in rows if row.kind == "BYOK"]
        assert len(byok) == 1, f"{name}: expected exactly one key row"
        assert byok[0].enabled is True, f"{name}: the key row must stay clickable"
        assert byok[0].label, f"{name}: the key row needs a label"


def test_the_key_row_says_remove_when_a_key_is_in_use():
    """Wording carries the affordance: set one up, or get rid of the one you
    have. A user whose picker is greyed is looking for the second."""
    off = [r for r in model_menu.build_rows([_record("a")]) if r.kind == "BYOK"][0]
    on = [r for r in model_menu.build_rows([_record("a")], byok_active=True)
          if r.kind == "BYOK"][0]

    assert off.label == model_menu.BYOK_SETUP_TEXT
    assert on.label == model_menu.BYOK_MANAGE_TEXT
    assert "remove" in on.label.lower()
    # `active` on this row means "a key is in use" (it drives the icon), not
    # "this is the current pick" as it does on a MODEL/THINKING row.
    assert on.active is True and off.active is False


def test_the_key_row_invokes_the_dialog_not_executes_it():
    """A Menu layout runs operators in an EXEC context, and the BYOK dialog
    operator does all its work in invoke() — execute() is a deliberate no-op.
    Without INVOKE_DEFAULT the row ran execute(), returned FINISHED and opened
    nothing, which is exactly what a user reported: "clicking does nothing".
    Pinned at source level because bpy is a MagicMock here."""
    import ast
    from pathlib import Path
    src = Path("src/scripts/mixar/modules/byok/ui/menus/agent_model_menu.py").read_text()
    tree = ast.parse(src)
    draw_row = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "_draw_row")
    # Find the `if row.kind == "BYOK":` branch and check its statements, in
    # order: operator_context is set to INVOKE_DEFAULT BEFORE the operator call.
    for node in ast.walk(draw_row):
        if not (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)):
            continue
        cmp = node.test
        if not (isinstance(cmp.comparators[0], ast.Constant)
                and cmp.comparators[0].value == "BYOK"):
            continue
        body = ast.unparse(ast.Module(body=node.body, type_ignores=[]))
        ctx_at = body.find("operator_context = 'INVOKE_DEFAULT'")
        op_at = body.find("mixar_byok.open_dialog")
        assert ctx_at != -1, "the key row must set operator_context = 'INVOKE_DEFAULT'"
        assert op_at != -1
        assert ctx_at < op_at, "operator_context must be set BEFORE the operator call"
        return
    raise AssertionError("no BYOK branch found in _draw_row")


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
