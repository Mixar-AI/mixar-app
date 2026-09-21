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
# Request bytes
# ---------------------------------------------------------------------------

class _CapturingService(AgentService):
    """Bypasses BaseService.__init__ — only the payload shaping is under test."""

    def __init__(self):  # noqa: D107 - see class docstring
        self.sent = None

    def put(self, path, json=None, **_kwargs):
        self.sent = (path, json)
        return SimpleNamespace(success=True, status_code=200, data={})

    def delete(self, path, **_kwargs):
        self.sent = (path, None)
        return SimpleNamespace(success=True, status_code=200, data={})

    def get(self, path, **_kwargs):
        self.sent = (path, None)
        return SimpleNamespace(success=True, status_code=200, data={})


def test_put_omits_thinking_level_entirely_when_none():
    """Byte-identical to a backend that predates the field."""
    service = _CapturingService()

    service.put_model_preference("anthropic", "claude-sonnet-4-6")

    path, payload = service.sent
    assert path == "model-preference"
    assert payload == {
        "provider": "anthropic", "model": "claude-sonnet-4-6", "role": "default",
    }
    assert "thinking_level" not in payload


def test_put_sends_the_thinking_level_when_one_is_chosen():
    service = _CapturingService()

    service.put_model_preference("anthropic", "m", thinking_level="high")

    assert service.sent[1]["thinking_level"] == "high"


def test_the_delete_endpoints_are_role_scoped_and_wholesale():
    service = _CapturingService()

    service.delete_model_preference()
    assert service.sent[0] == "model-preference/default"

    service.delete_model_preferences()
    assert service.sent[0] == "model-preference"


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

def _make_set_op(provider="anthropic", model="m", label="Anthropic · M",
                 thinking_level=""):
    op = agent_model_ops.MIXAR_OT_agent_model_set()
    op.provider, op.model, op.label = provider, model, label
    op.thinking_level = thinking_level
    op.reported = []
    op.report = lambda kinds, message: op.reported.append((kinds, message))
    return op


def _context():
    return SimpleNamespace(window_manager=SimpleNamespace())


@pytest.fixture
def captured_save(monkeypatch):
    calls = []
    monkeypatch.setattr(
        agent_model_ops.preference_client, "save_preference",
        lambda **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(agent_model_ops, "_redraw", lambda: None)
    return calls


def test_setting_a_model_writes_the_mirror_before_the_request_lands(captured_save):
    assert _make_set_op().execute(_context()) == {'FINISHED'}

    snapshot = preference_state.snapshot()
    assert snapshot["mixar_agent_model_id"] == "m"
    assert snapshot["mixar_agent_model_label"] == "Anthropic · M"
    assert captured_save[0]["provider"] == "anthropic"
    # "" means the model's own default and is translated to None, not sent.
    assert captured_save[0]["thinking_level"] is None


def test_a_thinking_row_forwards_its_level(captured_save):
    _make_set_op(thinking_level="high").execute(_context())

    assert captured_save[0]["thinking_level"] == "high"
    assert preference_state.snapshot()["mixar_agent_model_thinking"] == "high"


def test_the_optimistic_write_reverts_on_a_400(captured_save, monkeypatch):
    notified = []
    monkeypatch.setattr(
        agent_model_ops, "_notify_failure",
        lambda title, message: notified.append((title, message)),
    )
    preference_state.apply_local({
        "mixar_agent_model_provider": "openai",
        "mixar_agent_model_id": "gpt-5.5",
        "mixar_agent_model_label": "OpenAI · GPT-5.5",
    })
    before = preference_state.snapshot()

    _make_set_op().execute(_context())
    assert preference_state.snapshot()["mixar_agent_model_id"] == "m"

    captured_save[0]["on_done"](False, None, "Model not available: claude-x")

    assert preference_state.snapshot() == before
    # The server's message is user-safe per the contract — surfaced verbatim.
    assert notified == [("Could not change model", "Model not available: claude-x")]


def test_a_422_reverts_the_same_way(captured_save, monkeypatch):
    monkeypatch.setattr(agent_model_ops, "_notify_failure", lambda *_a: None)
    before = preference_state.snapshot()

    _make_set_op().execute(_context())
    captured_save[0]["on_done"](False, None, "Invalid form data — please reach out to support.")

    assert preference_state.snapshot() == before


def test_a_success_echo_is_adopted_without_a_second_round_trip(captured_save,
                                                               monkeypatch):
    refreshed = []
    monkeypatch.setattr(preference_state, "refresh", lambda: refreshed.append(1))

    _make_set_op().execute(_context())
    captured_save[0]["on_done"](True, {
        "byok_active": False,
        "items": [{
            "role": "default", "provider": "anthropic", "model": "m",
            "label": "Claude M", "thinking_level": "medium", "eligible": True,
        }],
    }, None)

    assert refreshed == []
    snapshot = preference_state.snapshot()
    assert snapshot["mixar_agent_model_label"] == "Claude M"
    # The server normalises the level; the mirror takes its word for it.
    assert snapshot["mixar_agent_model_thinking"] == "medium"


def test_a_late_success_after_logout_is_a_no_op(captured_save):
    """The epoch guard: restoring the logged-out account's pick in front of the
    next user is worse than leaving the cleared default."""
    _make_set_op().execute(_context())

    preference_state.clear()  # logout bumps the epoch
    captured_save[0]["on_done"](True, {
        "byok_active": False,
        "items": [{"role": "default", "provider": "anthropic", "model": "m",
                   "label": "Claude M"}],
    }, None)

    assert preference_state.snapshot()["mixar_agent_model_id"] == ""


def test_a_late_failure_after_logout_does_not_revert_the_cleared_state(
        captured_save, monkeypatch):
    monkeypatch.setattr(agent_model_ops, "_notify_failure", lambda *_a: None)
    preference_state.apply_local({"mixar_agent_model_id": "previous"})
    _make_set_op().execute(_context())

    preference_state.clear()
    captured_save[0]["on_done"](False, None, "Model not available: m")

    assert preference_state.snapshot()["mixar_agent_model_id"] == ""


def test_the_picker_refuses_to_write_while_byok_is_active(captured_save):
    preference_state.apply_local({"mixar_agent_model_byok_active": True})
    op = _make_set_op()

    assert op.execute(_context()) == {'CANCELLED'}
    assert captured_save == []
    assert op.reported and "API key" in op.reported[0][1]


def test_reset_clears_the_mirror_and_calls_delete(monkeypatch):
    calls = []
    monkeypatch.setattr(
        agent_model_ops.preference_client, "delete_preference",
        lambda **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(agent_model_ops, "_redraw", lambda: None)
    monkeypatch.setattr(preference_state, "refresh", lambda: None)
    preference_state.apply_local({
        "mixar_agent_model_id": "m", "mixar_agent_model_label": "M",
    })

    op = agent_model_ops.MIXAR_OT_agent_model_reset()
    op.report = lambda *_a: None
    assert op.execute(_context()) == {'FINISHED'}

    assert preference_state.snapshot()["mixar_agent_model_label"] == ""
    assert calls and "on_done" in calls[0]


def test_the_operators_are_auto_registered_through_a_classes_tuple():
    assert agent_model_ops.classes == (
        agent_model_ops.MIXAR_OT_agent_model_set,
        agent_model_ops.MIXAR_OT_agent_model_reset,
    )
    assert agent_model_ops.MIXAR_OT_agent_model_set.bl_idname == "mixar.agent_model_set"
    assert agent_model_ops.MIXAR_OT_agent_model_reset.bl_idname == "mixar.agent_model_reset"
