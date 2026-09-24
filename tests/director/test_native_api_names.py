# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every Blender API the Director C++ calls is one this repo already calls.

`upstream/` is a submodule and is not present in every checkout, so nothing
here can compile the overlay or read Blender's own headers. What it CAN do is
notice when Director reaches for a name that appears nowhere else in the
Mixar overlay — which is what an API remembered from an older Blender looks
like. Three build breaks on this branch were exactly that, the last being
`UI_ThemeClearColor`, renamed to `ui::theme::frame_buffer_clear` in 5.2 and
called that way by `view3d_agent_panel_draw.cc` two files away.

The allow-list below is the escape hatch, and the point of it: adding a name
to it is a deliberate "I checked this exists in Blender 5.2", which is the
exact moment each of those breaks skipped.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/source/blender"

#: Upstream APIs only Director uses. Each one has been read in upstream or
#: mirrored from a call site there; keep the reason with the name.
ALLOWED = {
    # Camera and object maths for the gate, the aerial map and the nudge.
    "BKE_camera_sensor_size",
    "BKE_object_apply_mat4",
    # View3D zoom helpers for the gate fit.
    "BKE_screen_view3d_zoom_from_fac",
    "BKE_screen_view3d_zoom_to_fac",
    "ED_view3d_win_to_3d_on_plane",
    # Depsgraph iteration flags for the aerial map's scene extents.
    "DEG_ITER_OBJECT_FLAG_LINKED_DIRECTLY",
    "DEG_ITER_OBJECT_FLAG_LINKED_VIA_SET",
    "DEG_ITER_OBJECT_FLAG_VISIBLE",
    # Headers included for their types only.
    "GPU_shader_shared_utils",
    "GPU_shader_shared",
    # The dock paints its keys as green dots rather than the theme's key-type
    # diamonds, so it sets the keyframe shader's shape flag itself
    # (GPU_shader_shared.hh, `GPUKeyframeShapes`).
    "GPU_KEYFRAME_SHAPE_CIRCLE",
    # Referenced in a comment about which operator a keymap item replaces.
    "WM_OT_context_set_int",
    # The dock's native keys (`view3d_director_timeline_keys.cc`): the keylist
    # API exactly as `channel_list_*` in upstream keyframes_draw.cc drives it
    # (ED_keyframes_keylist.hh at the pinned 5.2 commit).
    "ED_keylist_array",
    "ED_keylist_array_len",
    "ED_keylist_create",
    "ED_keylist_free",
    "ED_keylist_prepare_for_direct_access",
}

_PREFIXES = "UI|GPU|BKE|ED|WM|BLI|MEM|RNA|BLF|DEG|DRW"
_PATTERN = re.compile(rf"\b(?:{_PREFIXES})_[A-Za-z_0-9]+")


def _director_files() -> list[Path]:
    view3d = SOURCE / "editors/space_view3d"
    return sorted(view3d.glob("view3d_director*.cc")) + sorted(
        view3d.glob("view3d_director*.hh")
    )


def test_no_director_file_invents_an_api():
    director = _director_files()
    assert director, "no Director C++ found — the glob is wrong"
    names = {path.name for path in director}
    corpus = "\n".join(
        path.read_text(errors="ignore")
        for path in SOURCE.rglob("*")
        if path.suffix in {".cc", ".hh", ".h"} and path.name not in names
    )
    used: set[str] = set()
    for path in director:
        used |= set(_PATTERN.findall(path.read_text(encoding="utf-8")))

    unknown = sorted(
        name
        for name in used - ALLOWED
        if not re.search(rf"\b{re.escape(name)}\b", corpus)
    )
    assert not unknown, (
        "Director calls an API nothing else in the overlay calls — check it "
        "against Blender 5.2 and add it to ALLOWED with a reason:\n  "
        + "\n  ".join(unknown)
    )


def test_the_allow_list_has_no_dead_entries():
    """An entry that another file now also uses is a stale exemption."""
    director = _director_files()
    names = {path.name for path in director}
    corpus = "\n".join(
        path.read_text(errors="ignore")
        for path in SOURCE.rglob("*")
        if path.suffix in {".cc", ".hh", ".h"} and path.name not in names
    )
    used: set[str] = set()
    for path in director:
        used |= set(_PATTERN.findall(path.read_text(encoding="utf-8")))
    stale = sorted(
        name
        for name in ALLOWED
        if name not in used or re.search(rf"\b{re.escape(name)}\b", corpus)
    )
    assert not stale, "allow-list entries no longer needed:\n  " + "\n  ".join(stale)


def test_it_would_have_caught_the_break():
    """The regression that motivated it: `UI_ThemeClearColor` is 5.0's name."""
    timeline = (
        SOURCE / "editors/space_view3d/view3d_director_timeline.cc"
    ).read_text(encoding="utf-8")
    assert "UI_ThemeClearColor" not in timeline
    assert "ui::theme::frame_buffer_clear(TH_BACK);" in timeline
    assert "UI_ThemeClearColor" not in ALLOWED
    # And the name it should be is one the overlay already uses.
    agent_panel = (
        SOURCE / "editors/space_view3d/view3d_agent_panel_draw.cc"
    ).read_text(encoding="utf-8")
    assert "ui::theme::frame_buffer_clear(" in agent_panel


# -------------------------------------------------------------------------
# Headers pay for the names they use.


#: `ui::` names that are type ALIASES. A struct or class can be
#: forward-declared; an alias cannot, so a header that uses one must INCLUDE
#: the header that defines it. `view3d_director_cinema.hh` named
#: `ui::BlockCreateFunc` with neither, and compiled for months only because
#: every file that included it happened to include `UI_interface_c.hh` first.
#: The first one that did not broke the build with "'BlockCreateFunc': is not
#: a member of 'blender::ui'".
UI_ALIASES = {"BlockCreateFunc": "UI_interface_c.hh"}

#: Expressions that need a type DNA only forward-declares, and the header
#: that completes it. `ARegion::runtime` is an opaque pointer, so a file that
#: reaches through it compiles only with `BKE_screen.hh` — without it MSVC
#: says "use of undefined type 'blender::bke::ARegionRuntime'" and then
#: cascades into a bogus "function does not take 5 arguments", because the
#: ill-formed argument is simply dropped from the call.
OPAQUE_MEMBERS = {"region->runtime->": "BKE_screen.hh"}

#: Director helpers that take a MUTABLE `Scene *`. A file that holds the
#: scene as `const Scene *` and hands it to one of these fails with
#: "cannot convert argument 1 from 'const blender::Scene *'", which is easy
#: to write because a painter that only READS the scene reaches for `const`
#: by habit — and every one of these reads it too, through RNA that is not
#: const-correct.
MUTABLE_SCENE_CALLS = (
    "view3d_director_state_pointer(scene",
    "view3d_director_shot_camera(scene",
    "director_move_camera(scene",
    "view3d_director_state_read(scene",
    "view3d_director_active_shot_pointer(scene",
)


def test_files_include_for_the_opaque_types_they_reach_through():
    directory = SOURCE / "editors/space_view3d"
    sources = sorted(directory.glob("*.cc")) + sorted(directory.glob("*.hh"))
    assert sources, "no space_view3d sources found — the glob moved"
    for path in sources:
        source = path.read_text(encoding="utf-8")
        for expression, provider in OPAQUE_MEMBERS.items():
            if expression not in source:
                continue
            assert f'#include "{provider}"' in source, (
                f"{path.name} reaches through {expression}, whose type DNA only "
                f"forward-declares, without including {provider}"
            )


def test_a_scene_handed_to_a_director_helper_is_not_const():
    directory = SOURCE / "editors/space_view3d"
    for path in sorted(directory.glob("*.cc")):
        source = path.read_text(encoding="utf-8")
        if not any(call in source for call in MUTABLE_SCENE_CALLS):
            continue
        # Per FUNCTION, not per file: a `const Scene *scene` local in a
        # painter that only reads the scene is fine and common, and several
        # files hold both kinds. `\n}\n` is this suite's usual function-end
        # marker.
        for body in source.split("\n}\n"):
            if "const Scene *scene = " not in body:
                continue
            offender = next(
                (call for call in MUTABLE_SCENE_CALLS if call in body), None
            )
            assert offender is None, (
                f"{path.name} declares `const Scene *scene` and hands it to "
                f"`{offender}`, which takes a mutable Scene *"
            )


def test_headers_include_for_the_ui_aliases_they_name():
    headers = sorted((SOURCE / "editors/space_view3d").glob("view3d_director*.hh"))
    assert headers, "no Director headers found — the glob moved"
    for path in headers:
        source = path.read_text(encoding="utf-8")
        for alias, provider in UI_ALIASES.items():
            if f"ui::{alias}" not in source:
                continue
            assert f'#include "{provider}"' in source, (
                f"{path.name} names ui::{alias}, an alias that cannot be "
                f"forward-declared, without including {provider}"
            )


#: `float4x4::ptr()` yields `float[4][4]`, NOT `float *`, so the flat-indexing
#: habit from the C maths API (`m[0]`, `m[4]`, `m[8]`) does not even compile:
#: MSVC says "cannot convert from 'T [4][4]' to 'float *'". A matrix's columns
#: are written through `location()` / `x_axis()` / `y_axis()` / `z_axis()`,
#: which this overlay already assigns through; `ptr()` is for the 2D-array
#: APIs such as `BKE_object_apply_mat4`.
_FLAT_PTR = re.compile(r"\bfloat\s*\*[\s\w]*=\s*[^;]*\.ptr\(\)")


def test_no_matrix_ptr_is_bound_to_a_flat_float_pointer():
    directory = SOURCE / "editors/space_view3d"
    sources = sorted(directory.glob("*.cc")) + sorted(directory.glob("*.hh"))
    assert sources, "no space_view3d sources found — the glob moved"
    for path in sources:
        source = path.read_text(encoding="utf-8")
        offenders = [
            match.group(0).strip()
            for match in _FLAT_PTR.finditer(source)
            # A comment explaining the rule is not a violation of it.
            if not match.group(0).lstrip().startswith("*")
        ]
        assert not offenders, (
            f"{path.name} binds a `.ptr()` to a `float *`, but a float4x4's "
            "ptr() is a `float[4][4]` — assign through the axis accessors:\n  "
            + "\n  ".join(offenders)
        )
