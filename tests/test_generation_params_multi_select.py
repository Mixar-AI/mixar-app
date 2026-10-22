# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A catalog ``array`` parameter with published choices is a multi-select.

The sidebar engine builds it as a collection of tickable rows plus a hidden
active-row int, draws it with the one shared list, snapshots the ticks across
a catalog rebuild and collects the ticked values as a LIST in catalog order.
Nothing here names an animation preset: the feature is generic.
"""

import sys
from types import SimpleNamespace as NS
from unittest.mock import patch

from mixar.modules.common.generation_params.constants import (
    MULTI_SELECT_ACTIVE_SUFFIX,
    MULTI_SELECT_LIST_ID,
)
from mixar.modules.common.generation_params.core import (
    draw,
    engine,
    engine_values,
    multi_select,
)

ARRAY_SPEC = {
    "type": "array",
    "label": "Clips",
    "items": {"type": "string", "enum": ["a:x:one", "a:x:two", "a:y:three"]},
    "choices": [
        {"value": "a:x:one", "label": "One", "group": "x"},
        {"value": "a:x:two", "label": "Two", "group": "x"},
        {"value": "a:y:three", "label": "Three", "group": "y"},
    ],
    "default": ["a:x:two"],
}


class _Rows(list):
    """A CollectionProperty stand-in: add()/clear() over row namespaces."""

    def add(self):
        row = NS(value="", label="", group="", selected=False)
        self.append(row)
        return row

    def clear(self):
        del self[:]


def _rows(spec=ARRAY_SPEC, selected=()):
    rows = _Rows()
    multi_select.sync_choice_rows(rows, multi_select.spec_choices(spec), selected)
    return rows


# --------------------------------------------------------------------------- #
# Spec reading
# --------------------------------------------------------------------------- #


def test_choices_come_from_choices_then_items_enum_then_enum():
    assert [c["label"] for c in multi_select.spec_choices(ARRAY_SPEC)] == ["One", "Two", "Three"]
    assert multi_select.spec_choices(ARRAY_SPEC)[2]["group"] == "y"
    items_only = {"type": "array", "items": {"enum": ["p", "q"]}}
    assert multi_select.spec_choices(items_only) == [
        {"value": "p", "label": "p", "group": ""}, {"value": "q", "label": "q", "group": ""},
    ]
    assert multi_select.spec_choices({"enum": [1, None, ""]}) == [
        {"value": "1", "label": "1", "group": ""}]


def test_only_an_array_with_choices_is_a_multi_select():
    assert multi_select.is_multi_select(ARRAY_SPEC)
    assert not multi_select.is_multi_select({"type": "array"})
    assert not multi_select.is_multi_select({"type": "string", "enum": ["a", "b"]})
    assert multi_select.default_values(ARRAY_SPEC) == ["a:x:two"]
    assert multi_select.default_values({"default": "solo"}) == ["solo"]
    assert multi_select.default_values({}) == []


# --------------------------------------------------------------------------- #
# Rows and values
# --------------------------------------------------------------------------- #


def test_rows_mirror_the_catalog_and_tick_the_default():
    rows = _rows(selected=multi_select.default_values(ARRAY_SPEC))
    assert [(r.value, r.label, r.group, r.selected) for r in rows] == [
        ("a:x:one", "One", "x", False), ("a:x:two", "Two", "x", True),
        ("a:y:three", "Three", "y", False),
    ]
    assert multi_select.selected_values(rows) == ["a:x:two"]


def test_values_are_collected_in_catalog_order_not_tick_order():
    rows = _rows()
    multi_select.set_selected_values(rows, ["a:y:three", "a:x:one", "unknown"])
    assert multi_select.selected_values(rows) == ["a:x:one", "a:y:three"]


def test_summary_names_the_first_three_then_counts():
    assert multi_select.summary(_rows()) == "Nothing selected"
    assert multi_select.summary(_rows(selected=["a:x:one"])) == "One"
    many = {"type": "array", "choices": [{"value": str(i), "label": f"L{i}"} for i in range(5)]}
    assert multi_select.summary(_rows(many, selected=[str(i) for i in range(5)])) == (
        "L0, L1, L2 +2")


# --------------------------------------------------------------------------- #
# The WindowManager engine
# --------------------------------------------------------------------------- #


def test_the_engine_builds_a_row_collection_and_an_active_index():
    recorded = {}

    def collection(**kw):
        recorded["collection"] = kw
        return "COLLECTION"

    def integer(**kw):
        recorded.setdefault("ints", []).append(kw)
        return "INT"

    props = sys.modules["bpy.props"]
    with patch.object(props, "CollectionProperty", collection), \
            patch.object(props, "IntProperty", integer), \
            patch.object(engine.bpy.types, "PropertyGroup", type("PropertyGroup", (), {})), \
            patch.object(engine, "engine_row_class", lambda: "ROWCLS"):
        prop, value_map = engine._make_prop("clips", ARRAY_SPEC)
        assert prop == "COLLECTION" and value_map is None
        assert recorded["collection"]["type"] == "ROWCLS"
        _cls, schema = engine._build_group("svc", "model", {"clips": ARRAY_SPEC})
    entry = schema["clips"]
    assert entry["multi"] is True and entry["attr"] == "p_clips"
    assert recorded["ints"] == [{"name": "", "default": 0, "options": {"HIDDEN", "SKIP_SAVE"}}]


def test_values_read_and_write_as_lists_and_collect_as_a_list(monkeypatch):
    group = NS(p_clips=_rows(), p_clips__active=0)
    entry = {"spec": ARRAY_SPEC, "attr": "p_clips", "value_map": None, "multi": True}
    engine_values.write_param_value(group, entry, ["a:y:three", "a:x:one"])
    assert engine.read_param_value(group, entry) == ["a:x:one", "a:y:three"]

    monkeypatch.setattr(engine, "_schemas", {("svc", "m"): {"clips": entry}})
    monkeypatch.setattr(engine, "get_param_group", lambda service, model: group)
    assert engine.collect_params("svc", "m") == {"clips": ["a:x:one", "a:y:three"]}


def test_ticks_survive_a_catalog_rebuild_through_the_snapshot(monkeypatch):
    group = NS(p_clips=_rows(selected=["a:x:one"]))
    entry = {"spec": ARRAY_SPEC, "attr": "p_clips", "value_map": None, "multi": True}
    registered, schemas = {("svc", "m"): "wm_attr"}, {("svc", "m"): {"clips": entry}}
    monkeypatch.setattr(engine_values.bpy, "context", NS(window_manager=NS(wm_attr=group)))
    snapshot = engine_values.snapshot_values(registered, schemas)
    assert snapshot == {("svc", "m"): {"clips": ["a:x:one"]}}
    # The rebuild refills the rows from the spec (default ticked) ...
    engine_values.fill_choice_rows(registered, schemas)
    assert multi_select.selected_values(group.p_clips) == ["a:x:two"]
    # ... and the restore puts the user's ticks back.
    engine_values.restore_values(snapshot, registered, schemas)
    assert multi_select.selected_values(group.p_clips) == ["a:x:one"]
    # The engine's rebuild wires exactly these three around register_class.
    source = open(engine.__file__, encoding="utf-8").read()
    rebuild = source.split("def rebuild_from_catalog(")[1]
    assert rebuild.index("snapshot_values(_registered, _schemas)") < rebuild.index(
        "_teardown()") < rebuild.index("fill_choice_rows(_registered, _schemas)") < (
        rebuild.index("restore_values(snapshot, _registered, _schemas)"))


def test_the_widget_is_the_shared_list_with_a_summary():
    calls = []

    class _Layout:
        def column(self, align=False):
            return self

        def label(self, text="", translate=True):
            calls.append(("label", text))

        def template_list(self, *args, **kwargs):
            calls.append(("list", args, kwargs))

    group = NS(p_clips=_rows(selected=["a:x:one"]))
    entry = {"spec": ARRAY_SPEC, "attr": "p_clips", "value_map": None, "multi": True}
    draw._draw_widget(_Layout(), group, entry)
    assert calls[0] == ("label", "Clips")
    assert calls[1] == ("label", "One")
    kind, args, kwargs = calls[2]
    assert kind == "list"
    assert args == (MULTI_SELECT_LIST_ID, "p_clips", group, "p_clips", group,
                    "p_clips" + MULTI_SELECT_ACTIVE_SUFFIX)
    assert kwargs == {"rows": 6}


def test_the_list_filters_by_name_and_by_the_owners_group():
    from mixar.modules.common.generation_params.ui.lists import choice_list

    # The UIList base is a mock outside Blender; the flag logic is a function.
    ui_list = NS(bitflag_filter_item=1 << 30, filter_name="")
    rows = _rows()
    owner = NS(choices=rows, choice_filter="y")
    flags = choice_list.choice_filter_flags(ui_list, owner, "choices")
    # Rows of another group are hidden; a row with no group always shows.
    assert [bool(flag) for flag in flags] == [False, False, True]
    rows[0].group = ""
    assert [bool(f) for f in choice_list.choice_filter_flags(ui_list, owner, "choices")] == [
        True, False, True]
    owner.choice_filter = ""
    ui_list.filter_name = "tw"
    with patch.object(choice_list.UI_UL_list, "filter_items_by_name",
                      lambda pattern, flag, items, prop: [
                          flag if pattern in getattr(i, prop).lower() else 0 for i in items]):
        flags = choice_list.choice_filter_flags(ui_list, owner, "choices")
    assert [bool(flag) for flag in flags] == [False, True, False]
    source = (choice_list.__file__)
    assert "self.use_filter_show = True" in open(source, encoding="utf-8").read()


def test_a_filter_that_leaves_no_row_says_so_instead_of_an_empty_list():
    calls = []

    class _Layout:
        def column(self, align=False):
            return self

        def label(self, text="", translate=True, icon='NONE'):
            calls.append(("label", text))

        def template_list(self, *args, **kwargs):
            calls.append(("list",))

    owner = NS(choices=_rows(), active_choice=0, choice_filter="avian")
    multi_select.draw_multi_select(_Layout(), owner, "choices", "active_choice", "Animations")
    assert calls == [("label", "Animations"),
                     ("label", "No avian choices are available yet")]
    calls.clear()
    owner.choice_filter = "y"
    multi_select.draw_multi_select(_Layout(), owner, "choices", "active_choice", "Animations")
    assert calls[-1] == ("list",)
