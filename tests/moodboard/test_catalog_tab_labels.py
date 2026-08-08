# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sidebar tab labels are catalog data — never frozen client literals.

Blender consumes ``bl_label``/``bl_category`` once at registration, so the
moodboard panels resolve their labels through the catalog at registration
time and re-register (only) renamed tabs after a catalog swap. These tests
pin the label accessor's fallback contract and the refresh's "changed tabs
only / repeated swaps are no-ops" behaviour.
"""

import sys
from types import SimpleNamespace

import pytest

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

import bpy

bpy.types.Panel.bl_rna = SimpleNamespace(
    properties={"bl_space_type": SimpleNamespace(enum_items=[])}
)


def _live_bpy():
    """The bpy the code under test will import at call time.

    ``refresh_tab_labels`` does a fresh ``import bpy`` per call, and other
    test modules re-install the mock — patch whatever is in ``sys.modules``
    NOW, not the reference captured at this module's import.
    """
    return sys.modules["bpy"]

from mixar.bootstrap import generation_catalog_cache as CATALOG_CACHE
from mixar.bootstrap.generation_catalog.queries import GenerationCatalogQueries
from mixar.modules.moodboard.ui import moodboard_tab_labels as LABELS


@pytest.fixture(autouse=True)
def _clean_mapping():
    yield
    LABELS.init_capability_tabs({})


def _queries(payload):
    return GenerationCatalogQueries(lambda: payload)


def _fake_panel(label):
    return type(
        "FakePanel", (),
        {"bl_label": label, "bl_category": label, "is_registered": True},
    )


def test_get_capability_label_reads_payload_and_falls_back():
    loaded = _queries(
        {"capabilities": [{"key": "ai_render", "label": "Blockout Render"}]}
    )
    assert loaded.get_capability_label("ai_render", "AI Render") == "Blockout Render"
    # Unknown key, unloaded catalog, and blank labels all yield the fallback.
    assert loaded.get_capability_label("video_gen", "Video Gen") == "Video Gen"
    assert _queries(None).get_capability_label("ai_render", "AI Render") == "AI Render"
    blank = _queries({"capabilities": [{"key": "ai_render", "label": "   "}]})
    assert blank.get_capability_label("ai_render", "AI Render") == "AI Render"


def test_apply_catalog_labels_resolves_before_registration(monkeypatch):
    cls = _fake_panel("AI Render")
    LABELS.init_capability_tabs({"ai_render": (cls, "AI Render")})
    monkeypatch.setattr(
        CATALOG_CACHE, "get_capability_label",
        lambda key, default: {"ai_render": "Blockout Render"}.get(key, default),
    )
    LABELS.apply_catalog_labels()
    assert cls.bl_label == "Blockout Render"
    assert cls.bl_category == "Blockout Render"
    assert LABELS.get_tab_category("ai_render") == "Blockout Render"
    assert LABELS.get_tab_category("unknown", "Fallback") == "Fallback"


def test_refresh_reregisters_only_changed_tabs(monkeypatch):
    changed = _fake_panel("AI Render")
    unchanged = _fake_panel("Video Gen")
    LABELS.init_capability_tabs({
        "ai_render": (changed, "AI Render"),
        "video_gen": (unchanged, "Video Gen"),
    })
    monkeypatch.setattr(LABELS, "MIXIE_SPACE_AVAILABLE", True)
    monkeypatch.setattr(
        CATALOG_CACHE, "get_capability_label",
        lambda key, default: {"ai_render": "Blockout Render"}.get(key, default),
    )
    calls = []
    live_bpy = _live_bpy()
    monkeypatch.setattr(
        live_bpy.utils, "unregister_class",
        lambda c: calls.append(("unregister", c)),
    )
    monkeypatch.setattr(
        live_bpy.utils, "register_class",
        lambda c: calls.append(("register", c)),
    )

    LABELS.refresh_tab_labels()
    assert calls == [("unregister", changed), ("register", changed)]
    assert changed.bl_category == "Blockout Render"
    assert unchanged.bl_category == "Video Gen"

    # A repeated swap with identical labels must do nothing.
    calls.clear()
    LABELS.refresh_tab_labels()
    assert calls == []


def test_refresh_noop_when_mixie_space_unavailable(monkeypatch):
    cls = _fake_panel("AI Render")
    LABELS.init_capability_tabs({"ai_render": (cls, "AI Render")})
    monkeypatch.setattr(LABELS, "MIXIE_SPACE_AVAILABLE", False)
    monkeypatch.setattr(
        CATALOG_CACHE, "get_capability_label", lambda key, default: "Renamed"
    )
    calls = []
    monkeypatch.setattr(
        _live_bpy().utils, "unregister_class", lambda c: calls.append(c)
    )
    LABELS.refresh_tab_labels()
    assert calls == []
    assert cls.bl_category == "AI Render"
