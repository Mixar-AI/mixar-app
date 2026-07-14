# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for server-notification action buttons (store.push_from_server).

A server payload carrying ``action_url`` (+ optional ``action_label``) must
render a primary URL-carrying button — matching the update toast's Download
button — instead of the dimmed inline link.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.notifications.store import get_notification_store


def _get_item(store, nid):
    return next(i for i in store.get_visible() if i.id == nid)


def test_action_url_and_label_become_primary_button():
    store = get_notification_store()
    store.clear_all()
    nid = store.push_from_server({
        "id": "srv-1",
        "type": "info",
        "title": "New feature",
        "body": "Check out the new docs.",
        "action_url": "https://mixar.app/docs",
        "action_label": "View Docs",
    })
    item = _get_item(store, nid)
    assert len(item.actions) == 1
    action = item.actions[0]
    assert action.label == "View Docs"
    assert action.url == "https://mixar.app/docs"
    assert action.style == "primary"
    assert action.operator == ""
    # Button replaces the inline link — no double rendering.
    assert item.action_url is None
    assert item.server_id == "srv-1"


def test_action_url_without_label_defaults_to_open():
    store = get_notification_store()
    store.clear_all()
    nid = store.push_from_server({
        "id": "srv-2",
        "title": "Heads up",
        "action_url": "https://mixar.app/news",
    })
    item = _get_item(store, nid)
    assert [a.label for a in item.actions] == ["Open"]
    assert item.actions[0].url == "https://mixar.app/news"


def test_no_action_url_means_no_button():
    store = get_notification_store()
    store.clear_all()
    nid = store.push_from_server({
        "id": "srv-3",
        "title": "Plain notice",
        "body": "Nothing to click.",
    })
    item = _get_item(store, nid)
    assert item.actions == []
    assert item.action_url is None
