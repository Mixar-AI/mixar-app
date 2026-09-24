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
# Preference mirror
# ---------------------------------------------------------------------------

def test_the_payload_parser_prefers_the_default_role():
    preference_state.apply_from_payload({
        "byok_active": True,
        "items": [
            {"role": "worker", "provider": "openai", "model": "gpt-5.5"},
            {"role": "default", "provider": "anthropic", "model": "m",
             "label": "Claude M", "thinking_level": "low", "eligible": False},
        ],
    })

    snapshot = preference_state.snapshot()
    assert snapshot["mixar_agent_model_provider"] == "anthropic"
    assert snapshot["mixar_agent_model_label"] == "Claude M"
    assert snapshot["mixar_agent_model_thinking"] == "low"
    assert snapshot["mixar_agent_model_eligible"] is False
    assert snapshot["mixar_agent_model_byok_active"] is True


def test_an_absent_eligible_flag_fails_open():
    preference_state.apply_from_payload({
        "items": [{"role": "default", "provider": "p", "model": "m"}],
    })

    assert preference_state.snapshot()["mixar_agent_model_eligible"] is True
    # No label from an older backend -> fall back to the model id, never blank.
    assert preference_state.snapshot()["mixar_agent_model_label"] == "m"


def test_a_failed_fetch_keeps_the_cached_pick(monkeypatch):
    preference_state.apply_from_payload({
        "items": [{"role": "default", "provider": "p", "model": "m",
                   "label": "M"}],
    })
    monkeypatch.setattr(preference_state, "apply_to_wm", lambda *_a, **_k: None)

    preference_state._apply_fetch_result(
        preference_state.current_epoch(), False, None, "boom"
    )

    assert preference_state.snapshot()["mixar_agent_model_label"] == "M"


def test_a_fetch_that_lands_after_logout_is_dropped(monkeypatch):
    monkeypatch.setattr(preference_state, "apply_to_wm", lambda *_a, **_k: None)
    epoch = preference_state.current_epoch()

    preference_state.clear()
    preference_state._apply_fetch_result(epoch, True, {
        "items": [{"role": "default", "provider": "p", "model": "m",
                   "label": "Previous account"}],
    }, None)

    assert preference_state.snapshot()["mixar_agent_model_label"] == ""


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def test_logout_clears_the_pick_through_invalidate_agent_settings(monkeypatch):
    from mixar.modules.auth.core import auth_hooks

    monkeypatch.setattr(
        auth_hooks, "logger", SimpleNamespace(warning=lambda *_a, **_k: None)
    )
    preference_state.apply_from_payload({
        "items": [{"role": "default", "provider": "p", "model": "m", "label": "M"}],
    })

    auth_hooks.invalidate_agent_settings()

    assert preference_state.snapshot()["mixar_agent_model_label"] == ""


def test_the_inline_logout_path_does_not_clear_the_pick_a_second_time():
    """Two owners of one clear gave an in-flight worker two orderings to win in
    — `invalidate_agent_settings()` is the only one."""
    source = AUTH_OPS_SOURCE.read_text(encoding="utf-8")
    assert "preference_state" not in source
    for name in WM_PROPS:
        assert name not in source


def test_a_catalog_swap_refreshes_the_pick_but_a_disk_restore_does_not():
    from mixar.modules.byok.core import models_cache

    source = (
        SCRIPTS / "mixar" / "modules" / "byok" / "core" / "models_cache.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)

    def _calls(function_name):
        node = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == function_name
        )
        return {
            call.func.id
            for call in ast.walk(node)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        }

    # The apply closure inside _schedule_populate is the network path.
    assert "_refresh_preference" in _calls("_schedule_populate")
    # Bootstrap phase 3 runs before the login hook — a disk restore would spend
    # a guaranteed 401.
    assert "_refresh_preference" not in _calls("load_from_disk")
    assert hasattr(models_cache, "_refresh_preference")


def test_a_plan_change_invalidates_the_catalog_but_a_flap_does_not():
    from mixar.modules.common.usage.core import state

    subscribed = state.UsageSnapshot(
        has_subscription=True, plan_slug="pro", fetched_at=100.0
    )
    upgraded = state.UsageSnapshot(
        has_subscription=True, plan_slug="studio", fetched_at=200.0
    )
    free = state.UsageSnapshot(has_subscription=False, fetched_at=200.0)

    assert state.tier_changed(subscribed, upgraded) is True
    assert state.tier_changed(subscribed, free) is True
    assert state.tier_changed(subscribed, subscribed) is False
    # A failed fetch copies the previous figures forward — it proves nothing.
    assert state.tier_changed(subscribed, state.snapshot_error("offline", now=300.0)) \
        is False
    # The first reading of a session is login's job, not a "change".
    assert state.tier_changed(state.EMPTY, subscribed) is False


def test_a_local_write_repaints_both_surfaces(monkeypatch):
    """The optimistic write AND the revert must redraw.

    The footer and the island live in separate windows, so the menu click that
    closes over one leaves the other holding the old label. The revert is the
    case that actually hurts: the server refuses the pick, `apply_local`
    restores the previous value, and without a redraw the user goes on reading
    a model that was rejected. Caught in the running app — state said the
    button was disabled while the pixels were an untouched stale frame.
    """
    calls = []
    monkeypatch.setattr(preference_state, "_redraw", lambda: calls.append(True))

    preference_state.apply_local({"mixar_agent_model_label": "Claude Sonnet 4.6"})
    assert calls == [True], "the optimistic write did not repaint"

    preference_state.apply_local({"mixar_agent_model_label": ""})
    assert calls == [True, True], "the revert did not repaint"


def test_a_stale_epoch_local_write_does_not_repaint(monkeypatch):
    """A dropped write must not repaint either — nothing changed."""
    calls = []
    monkeypatch.setattr(preference_state, "_redraw", lambda: calls.append(True))

    assert preference_state.apply_local({"mixar_agent_model_label": "X"},
                                        epoch=preference_state.current_epoch() + 99) is False
    assert calls == []


def test_server_provider_prefix_is_not_shown_in_the_chip():
    preference_state.apply_from_payload({"items": [{
        "provider": "anthropic", "model": "m", "label": "Anthropic · Claude M",
    }]})
    assert preference_state.snapshot()["mixar_agent_model_label"] == "Claude M"
