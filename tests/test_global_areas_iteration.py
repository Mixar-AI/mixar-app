# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""`Window.global_areas` yields AREAS, so nothing may walk a `.areas` on it.

The property is Mixar's own RNA addition (`rna_wm_mixar.cc`), and its
collection getter iterates `win->global_areas.areabase` DIRECTLY — upstream's
`ScrAreaMap` never reaches Python, so there is no `.areas` attribute to walk.

Getting this wrong is invisible until runtime and then only inside whatever
callback touched it: the topbar slider's redraw pump shipped
`global_areas.areas` and raised

    AttributeError: bpy_prop_collection: attribute "areas" not found

out of a `bpy.app.timers` callback on every single mode switch. The timer
kept re-registering, so the traceback repeated rather than announcing itself
once, and the slider's thumb never animated.

The topbar is a global area and is genuinely absent from `screen.areas`, so
this property is the only way to tag it — which is why several modules reach
for it and why the shape is worth pinning in one place.
"""

import ast
import re
from pathlib import Path

MODULES = Path(__file__).resolve().parent.parent / "src" / "scripts" / "mixar" / "modules"

# Every module that tags or inspects a global area.
USERS = [
    "workflow/ui/operators/mode_slider_anim.py",
    "common/updates/ui/topbar_badge.py",
    "common/usage/core/poller.py",
    "director/ui/properties/director_properties.py",
    "onboarding/core/tour_driver.py",
    "onboarding/core/overlay/highlight.py",
    "onboarding/core/overlay/overlay_renderer.py",
]


def _sources():
    for rel in USERS:
        path = MODULES / rel
        assert path.exists(), f"{rel} moved — update this list, don't delete the pin"
        yield rel, path.read_text(encoding="utf-8")


def test_nothing_walks_a_dot_areas_on_global_areas():
    """The exact bug: `for area in window.global_areas.areas`."""
    offenders = [
        rel for rel, src in _sources() if re.search(r"global_areas\s*\)?\s*\.areas\b", src)
    ]
    assert not offenders, (
        f"{offenders}: `Window.global_areas` is already the area collection — "
        "iterate it directly. `.areas` raises AttributeError at runtime."
    )


def test_no_attribute_is_read_off_the_collection():
    """`.areas` was the one that shipped, but any sub-attribute fails alike.

    Parsed rather than grepped: these files legitimately NAME
    `win->global_areas.areabase` in prose when explaining where the
    collection comes from, and a regex over raw text cannot tell that from
    code. `ast` sees only what actually executes.

    Readers consume the collection in two shapes and both are fine — a
    direct `for area in ...` and `areas.extend(globals_coll)`. What is never
    fine is reaching THROUGH it for another collection.
    """
    for rel, src in _sources():
        tree = ast.parse(src)
        for node in ast.walk(tree):
            # `<anything>.global_areas.<attr>`
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
                assert node.value.attr != "global_areas", (
                    f"{rel}: reads `.{node.attr}` off global_areas; the "
                    "property IS the collection of areas."
                )
            # `getattr(window, "global_areas", ...).<attr>`
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "getattr"
                and len(node.value.args) >= 2
                and isinstance(node.value.args[1], ast.Constant)
                and node.value.args[1].value == "global_areas"
            ):
                raise AssertionError(
                    f"{rel}: reads `.{node.attr}` off a global_areas getattr; "
                    "the property IS the collection of areas."
                )


def test_the_slider_pump_still_tags_only_topbars():
    """The pump exists to animate the Zen/Engine thumb; tagging every global
    area (the status bar included) would repaint more than it needs at 60fps."""
    src = (MODULES / "workflow/ui/operators/mode_slider_anim.py").read_text(encoding="utf-8")
    assert "global_areas" in src
    assert "area.type == 'TOPBAR'" in src
    assert "area.tag_redraw()" in src
