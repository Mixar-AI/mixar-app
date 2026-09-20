# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for library-browse chat-mode hardening.

Pins two fixes:

1. ``_grid_bubble`` must not hold a ``CollectionProperty`` item wrapper across a
   ``.remove()`` — a removal reallocates the backing store and invalidates any
   previously fetched wrapper (dereferencing a stale one can crash/deadlock
   Blender). The kept bubble must be re-fetched fresh AFTER every removal.

2. The semantic-search worker must publish its result ONLY while its token is
   still current, so a stale worker that finishes after a newer search cannot
   clobber the newer result (which would strand the newer bubble on
   "Searching…").

bpy is stubbed by the root conftest, so these run outside Blender.
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from mixar.modules.space_mixie_chat.core import library_browse as lb


# --------------------------------------------------------------------------- #
# _grid_bubble: fresh-wrapper-after-remove contract
# --------------------------------------------------------------------------- #

class _Bubble:
    def __init__(self, bubble_id="", actions=None):
        self.bubble_id = bubble_id
        self.action_items = actions or []
        self.sender = "AGENT"
        self.message_type = ""
        self._op_seq = 0


class _FakeColl:
    """Mimics scene.mixie_chat_messages closely enough to expose a stale-wrapper
    bug: every ``__getitem__``/``add`` hands back a wrapper stamped with the
    monotonic op sequence at which it was produced, and ``remove`` shifts the
    store. A fix that returns a pre-remove wrapper is caught by asserting the
    returned wrapper was produced AFTER the last removal."""

    def __init__(self, items):
        self._items = list(items)
        self.ops = []
        self._seq = 0

    def __len__(self):
        return len(self._items)

    def __getitem__(self, i):
        self._seq += 1
        self.ops.append(("get", i, self._seq))
        w = self._items[i]
        w._op_seq = self._seq
        return w

    def remove(self, i):
        self._seq += 1
        self.ops.append(("remove", i, self._seq))
        del self._items[i]

    def add(self):
        self._seq += 1
        self.ops.append(("add", None, self._seq))
        b = _Bubble()
        b._op_seq = self._seq
        self._items.append(b)
        return b


def _lib(bid):
    return _Bubble(bubble_id=lb.LIBRARY_BUBBLE_PREFIX + bid)


def _picker():
    # A stale agent asset-picker: action items carry an asset_name.
    return _Bubble(actions=[SimpleNamespace(value="", asset_name="Chair")])


def _plain():
    return _Bubble(bubble_id="chat:1")


def _last_remove_seq(coll):
    return max((s for (op, _, s) in coll.ops if op == "remove"), default=0)


def test_grid_bubble_keeps_newest_and_returns_fresh_wrapper():
    # Two library bubbles + a stale picker + a plain message.
    coll = _FakeColl([_plain(), _lib("aaaa"), _picker(), _lib("bbbb")])
    scene = SimpleNamespace(mixie_chat_messages=coll)

    keep = lb._grid_bubble(scene)

    # Exactly one library bubble survives, and it is the newest ("bbbb").
    remaining = [m for m in coll._items if str(m.bubble_id).startswith(lb.LIBRARY_BUBBLE_PREFIX)]
    assert len(remaining) == 1
    assert keep.bubble_id == lb.LIBRARY_BUBBLE_PREFIX + "bbbb"
    # The plain message is untouched; the stale picker and older grid are gone.
    assert any(m.bubble_id == "chat:1" for m in coll._items)
    assert not any(getattr(a, "asset_name", "") for m in coll._items for a in m.action_items)
    # The returned wrapper was produced AFTER the last removal (not a stale one).
    assert keep._op_seq > _last_remove_seq(coll)


def test_grid_bubble_creates_one_when_absent():
    coll = _FakeColl([_plain()])
    scene = SimpleNamespace(mixie_chat_messages=coll)

    keep = lb._grid_bubble(scene)

    assert str(keep.bubble_id).startswith(lb.LIBRARY_BUBBLE_PREFIX)
    assert keep._op_seq > _last_remove_seq(coll)


def test_grid_bubble_protects_live_picker(monkeypatch):
    # When the agent is awaiting input, a live (non-library) picker must survive.
    monkeypatch.setattr(lb, "_agent_awaiting_input", lambda scene: True)
    coll = _FakeColl([_picker(), _lib("bbbb")])
    scene = SimpleNamespace(mixie_chat_messages=coll)

    keep = lb._grid_bubble(scene)

    assert keep.bubble_id == lb.LIBRARY_BUBBLE_PREFIX + "bbbb"
    # The live picker is left alone.
    assert any(getattr(a, "asset_name", "") for m in coll._items for a in m.action_items)


# --------------------------------------------------------------------------- #
# semantic search worker: stale-token guard
# --------------------------------------------------------------------------- #

def _install_fake_client(monkeypatch, results):
    resp = SimpleNamespace(
        success=True,
        status_code=200,
        message="",
        data={"data": {"results": results}},
    )
    client = SimpleNamespace(post=lambda *a, **k: resp)
    api_mod = sys.modules.setdefault(
        "mixar.modules.asset_search.core.api_client",
        MagicMock(name="api_client"),
    )
    monkeypatch.setattr(api_mod, "metered_client", lambda: client, raising=False)
    const_mod = sys.modules.setdefault(
        "mixar.modules.asset_search.constants",
        MagicMock(name="asset_constants"),
    )
    monkeypatch.setattr(const_mod, "ASSET_SEARCH_ENDPOINT", "/search", raising=False)


def test_worker_ignores_stale_token(monkeypatch):
    _install_fake_client(monkeypatch, results=[])
    monkeypatch.setattr(lb, "_search_payload", None, raising=False)
    monkeypatch.setattr(lb, "_search_token", 5, raising=False)

    # A stale worker (token 3) finishing while the current token is 5 must NOT
    # publish — otherwise it strands the current search's bubble.
    lb._semantic_search_worker("old query", token=3)
    assert lb._search_payload is None


def test_worker_publishes_current_token(monkeypatch):
    _install_fake_client(monkeypatch, results=[
        {"metadata": {"name": "Chair", "blend_file": "a.blend"},
         "similarity_score": 0.9},
    ])
    monkeypatch.setattr(lb, "_search_payload", None, raising=False)
    monkeypatch.setattr(lb, "_search_token", 7, raising=False)

    lb._semantic_search_worker("live query", token=7)
    assert lb._search_payload is not None
    token, query, had_image, result = lb._search_payload
    assert token == 7
    assert result["success"] is True
    assert result["results"][0]["name"] == "Chair"
