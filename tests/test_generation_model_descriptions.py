# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A catalog model's ``description`` reaches the model picker.

Every catalog Model dropdown row shows it as its hover tooltip, and the
selected model's text sits as muted wrapped lines under the dropdown. It is
server text (localized by the backend), so it never passes through the
client's translation. Nothing here names a real model: the feature is generic.
"""

from types import SimpleNamespace as NS

import pytest

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.bootstrap import generation_catalog_cache as CATALOG_CACHE
from mixar.modules.common.generation_params.constants import (
    MODEL_DESCRIPTION_WRAP_COLUMNS,
)
from mixar.modules.common.generation_params.core import draw, selector

LONG = ("Creatures with many legs or none at all. Takes the matching presets; "
        "a different body rigged here cannot use them.")


def _catalog(models):
    return {
        "catalog_version": "desc-v1",
        "capabilities": [{
            "key": "cap",
            "services": [{"key": "svc", "surface": "moodboard", "models": models}],
        }],
    }


@pytest.fixture
def catalog():
    saved = CATALOG_CACHE._catalog

    def install(models):
        with CATALOG_CACHE._lock:
            CATALOG_CACHE._catalog = _catalog(models)
            CATALOG_CACHE._bump_enum_version_locked()

    yield install
    with CATALOG_CACHE._lock:
        CATALOG_CACHE._catalog = saved
        CATALOG_CACHE._bump_enum_version_locked()


class Layout:
    def __init__(self, events=None):
        self.events = [] if events is None else events
        self.active = True
        self.scale_y = 1.0

    def column(self, **_kwargs):
        child = Layout(self.events)
        self.events.append(("column", child))
        return child

    row = column

    def label(self, **kwargs):
        self.events.append(("label", kwargs, self))

    def prop(self, _data, name, **_kwargs):
        self.events.append(("prop", name))


def test_dropdown_rows_carry_the_model_description_or_fall_back_to_the_label(catalog):
    catalog([
        {"slug": "a", "label": "Model A", "description": "  Best for A.  "},
        {"slug": "b", "label": "Model B", "description": ""},
        {"slug": "c", "label": "Model C"},  # a backend that predates the field
        {"slug": "d", "label": "Model D", "description": None},
        {"slug": "e", "label": "Model E", "description": "   "},
    ])
    items = CATALOG_CACHE.get_model_enum_items("svc")
    assert items == [
        ("a", "Model A", "Best for A."),
        ("b", "Model B", "Model B"),
        ("c", "Model C", "Model C"),
        ("d", "Model D", "Model D"),
        ("e", "Model E", "Model E"),
    ]
    # Memoized: Blender keeps raw char* into these strings between redraws.
    assert CATALOG_CACHE.get_model_enum_items("svc") is items


def test_description_lines_are_wrapped_muted_and_untranslated(catalog):
    catalog([{"slug": "a", "label": "Model A", "description": LONG}])
    layout = Layout()
    assert draw.draw_model_description(layout, "svc", "a") is True
    (_, col), *labels = layout.events
    assert col.active is False and col.scale_y < 1.0
    assert len(labels) > 1
    assert all(kw["translate"] is False and owner is col for _, kw, owner in labels)
    texts = [kw["text"] for _, kw, _ in labels]
    assert all(len(text) <= MODEL_DESCRIPTION_WRAP_COLUMNS for text in texts)
    assert " ".join(texts) == LONG


def test_description_wraps_to_the_measured_host_width(catalog, monkeypatch):
    """With a known width each line fits it in the UI font (a label ellipsizes overflow)."""
    import sys
    from mixar.modules.common.generation_params.constants import MODEL_DESCRIPTION_MARGIN

    char_px = 6
    blf = NS(size=lambda *_a: None, dimensions=lambda _f, text: (len(text) * char_px, 10))
    monkeypatch.setitem(sys.modules, "blf", blf)
    prefs = NS(ui_styles=[NS(widget=NS(points=12))], system=NS(ui_scale=1.0))
    monkeypatch.setattr(sys.modules["bpy"], "context", NS(preferences=prefs, region=None),
                        raising=False)
    catalog([{"slug": "a", "label": "Model A", "description": LONG}])
    for width in (240, 480):
        layout = Layout()
        assert draw.draw_model_description(layout, "svc", "a", width=width) is True
        texts = [kw["text"] for _, kw, _ in layout.events[1:]]
        assert all(len(t) * char_px <= width - MODEL_DESCRIPTION_MARGIN for t in texts)
        assert " ".join(texts) == LONG
        if width == 480:
            assert len(texts) < narrow
        narrow = len(texts)


@pytest.mark.parametrize("service, slug", [("svc", "b"), ("svc", "missing"), ("", "a"),
                                           ("svc", ""), ("other", "a")])
def test_no_description_draws_nothing(catalog, service, slug):
    catalog([{"slug": "a", "label": "Model A", "description": LONG},
             {"slug": "b", "label": "Model B", "description": ""}])
    layout = Layout()
    assert draw.draw_model_description(layout, service, slug) is False
    assert layout.events == []


def test_capability_selector_draws_the_description_under_the_model_dropdown(
        catalog, monkeypatch):
    catalog([{"slug": "a", "label": "Model A", "description": "Best for A."}])
    monkeypatch.setattr(selector, "draw_service_params",
                        lambda layout, *_a: layout.events.append(("params",)))
    layout = Layout()
    tab = NS(mode="svc", model="a")
    assert selector.draw_capability_selector(layout, tab, "cap") is True
    kinds = [event[0] if event[0] != "label" else event[1]["text"]
             for event in layout.events if event[0] != "column"]
    assert kinds == ["prop", "Best for A.", "params"]
