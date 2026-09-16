# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared doubles for the open-run suites (test_open_run, test_socket_turns).

Not a test module: pytest puts this directory on sys.path (no __init__.py),
so the suites ``from _open_run_support import ...``. Fixtures imported by
name into a test module are collected like local ones.
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_SRC_SCRIPTS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), *([".."] * 4))
)
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

for _dep in ("keyring", "keyring.errors", "websocket", "requests", "jwt",
             "sentry_sdk", "bpy.utils.previews"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.space_mixie_chat.core import turn_events  # noqa: E402
from mixar.modules.space_mixie_chat.core.session import SessionManager  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _Messages(list):
    """scene.mixie_chat_messages stand-in."""

    def add(self):
        msg = SimpleNamespace(sender='', text='', bubble_id='', loader_visible=False,
                              loader_texts='', delivery_hint='', content='',
                              feedback_visible=False, attachments=_Messages())
        self.append(msg)
        return msg

    def remove(self, idx):
        del self[idx]


class _Scenes(list):
    def get(self, name):
        return next((s for s in self if s.name == name), None)


def _scene(name="Scene", session_id="sid-1", state="IDLE"):
    return SimpleNamespace(
        name=name, mixie_session_id=session_id, mixie_chat_state=state,
        mixie_chat_is_busy=False, mixie_run_open=False, mixie_run_id="",
        mixie_chat_active_turn_mode="", mixie_chat_mode="AGENT",
        mixie_chat_cat_activity="", mixie_chat_cat_activity_until="",
        mixie_chat_input="", mixie_chat_messages=_Messages(),
    )


@pytest.fixture(autouse=True)
def clean_state():
    SessionManager.reset()
    turn_events.reset()
    yield
    SessionManager.reset()
    turn_events.reset()


@pytest.fixture
def live_bpy(monkeypatch):
    """The bpy the modules resolve at call time (they ``import bpy`` inside
    functions), so patching this mock is what they see."""
    bpy = sys.modules["bpy"]
    monkeypatch.setattr(bpy.data, "scenes", _Scenes(), raising=False)
    return bpy
