# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The glass kit's contracts, pinned at source level.

The kit is GPU C++, and in this overlay there is no `gpu` module to build
against and no compiler to build with, so none of it can be exercised. Each
contract below is a failure that would be INVISIBLE at runtime, which is why
none of them can be left to a test that runs the code:

* a token row that zero-fills its alpha draws NOTHING, and the report is
  "the button is missing", not a colour bug;
* a layer that forgets to multiply by ``style.alpha`` stays on screen in a pane
  the app believes it has faded out -- visibly "stuck" long after dismissal;
* a ``Mixar_WindowSetBlurBehind`` call outside the Apple/Windows guard is an
  undefined reference on Linux, and the link error, not a pixel, is the signal;
* a pane drawn with the plain image shader cannot weight its sample, so the
  reveal animation pops the backdrop in instead of fading it;
* a cascade stage that blurs nothing and a chain that frees nothing both look
  exactly like a working pane at one frame.

Run with the repo venv: ``python -m pytest -q`` from the repository root.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ED = ROOT / "src" / "source" / "blender" / "editors"

HEADER = (ED / "include" / "ED_mixar_glass.hh").read_text(encoding="utf-8")
KIT_PATH = ED / "interface" / "interface_mixar_liquid_glass.cc"
TOKENS_PATH = ED / "interface" / "interface_mixar_liquid_glass_tokens.cc"
DRAW_PATH = ED / "interface" / "interface_mixar_liquid_glass_draw.cc"
KIT = KIT_PATH.read_text(encoding="utf-8")
TOKENS = TOKENS_PATH.read_text(encoding="utf-8")
DRAW = DRAW_PATH.read_text(encoding="utf-8")
CMAKE = (ED / "interface" / "CMakeLists.txt").read_text(encoding="utf-8")

#: The roles, in enum order. The enum and the token table are read together.
ROLES = ["card", "menu", "panel", "island", "pill", "chat", "chip", "moodboard"]

#: `MixarGlassTokens` in declaration order. The table is initialised
#: positionally, so a reordering here silently re-tones a surface.
STRUCT_FIELDS = [
    "tint_top",
    "tint_bottom",
    "glaze",
    "sheen",
    "rim",
    "refract",
    "shadow",
    "radius",
    "rim_width",
    "blur_radius",
    "shadow_width",
    "sheen_height",
    "specular_width",
    "specular_alpha",
    "specular_period",
]
COLOUR_FIELDS = STRUCT_FIELDS[:7]

#: Everything `ED_mixar_glass.hh` promises, defined exactly once.
PUBLIC_API = [
    "mixar_glass_tokens",
    "mixar_glass_backdrop_prepare",
    "mixar_glass_draw",
    "mixar_glass_window_apply_translucency",
    "mixar_glass_free",
]

WINDOW_GUARD = "defined(__APPLE__) || defined(_WIN32)"


def _table() -> str:
    """The token table's text, from its first row to the `static_assert`."""
    start = TOKENS.index("const MixarGlassTokens g_glass_tokens[] = {")
    return TOKENS[start : TOKENS.index("static_assert(BLI_ARRAY_SIZE", start)]


def _rows() -> dict[str, str]:
    """Role name -> that role's row body."""
    parts = re.split(r"/\*\s*(MIXAR_GLASS_[A-Z]+).*?\*/", _table(), flags=re.DOTALL)
    names = (name.removeprefix("MIXAR_GLASS_").lower() for name in parts[1::2])
    return dict(zip(names, parts[2::2]))


def _code(src: str) -> str:
    """A file with its comments removed.

    Several contracts are about the CODE -- no RNG call, no unit conversion, a
    pass that replaces rather than blends -- and the neighbouring prose names
    the very thing being forbidden ("time-driven, not random", "wraps its own
    radians in `RAD2DEGF`"), so the prose has to be out of the way first.
    """
    without_blocks = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", without_blocks)


def _lines_outside_window_guard(src: str, needles: list[str]) -> list[str]:
    """Lines that mention a needle while NOT inside an Apple/Windows `#if`."""
    in_guard: set[int] = set()
    depth = 0
    bad: list[str] = []
    for lineno, line in enumerate(src.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#if"):
            depth += 1
            if WINDOW_GUARD in stripped:
                in_guard.add(depth)
        elif stripped.startswith("#else") or stripped.startswith("#elif"):
            # The else branch of a guard is not the guarded branch.
            in_guard.discard(depth)
        elif stripped.startswith("#endif"):
            in_guard.discard(depth)
            depth -= 1
        if not in_guard and any(needle in line for needle in needles):
            bad.append(f"{lineno}: {stripped}")
    return bad


class TestEveryRoleHasItsOwnRow:
    def test_the_enum_and_the_table_are_in_the_same_order(self) -> None:
        """One table row per enum value, and in the same order.

        `mixar_glass_tokens` indexes the enum straight into the table, so a row
        added at the end and an enum value added in the middle would hand one
        surface another surface's material -- a tint swap with no error.
        """
        enum_body = HEADER[
            HEADER.index("enum eMixarGlassRole {") : HEADER.index("};", HEADER.index("enum"))
        ]
        names = [n.lower() for n in re.findall(r"^\s*MIXAR_GLASS_([A-Z]+),", enum_body, re.M)]
        assert names == ROLES, f"the enum grew or reordered: {names}"
        assert list(_rows()) == ROLES, f"the table grew or reordered: {list(_rows())}"

    def test_the_static_assert_covers_every_role(self) -> None:
        assert "BLI_ARRAY_SIZE(g_glass_tokens) == size_t(MIXAR_GLASS_MOODBOARD) + 1u" in TOKENS, (
            "Without the assert a new role compiles and reads past the table."
        )


class TestEveryColourStatesItsAlpha:
    def test_each_row_carries_the_seven_colours_in_declaration_order(self) -> None:
        for role, body in _rows().items():
            found = re.findall(r"/\*\s*([a-z_]+)\s*\*/", body)
            assert found == STRUCT_FIELDS, (
                f"{role} does not fill MixarGlassTokens field by field, in order: "
                f"{found}. The initialiser is positional."
            )

    def test_every_colour_group_names_all_four_components(self) -> None:
        """A three-value initialiser zero-fills the alpha: the pane disappears.

        That failure reads to the user as a missing button, and it is why every
        entry spells its alpha out even when it is zero.
        """
        for role, body in _rows().items():
            groups = re.findall(r"\{([^{}]*)\}", body)
            assert len(groups) == len(COLOUR_FIELDS), (
                f"{role} has {len(groups)} colour groups, not {len(COLOUR_FIELDS)}"
            )
            for group, field in zip(groups, COLOUR_FIELDS):
                parts = [p.strip() for p in group.split(",")]
                assert len(parts) == 4, (
                    f"{role}.{field} states {len(parts)} components, so its alpha is "
                    f"implicit: {group}"
                )

    def test_the_structs_field_order_is_the_one_the_table_fills(self) -> None:
        struct_body = HEADER[
            HEADER.index("struct MixarGlassTokens {") : HEADER.index(
                "};", HEADER.index("struct MixarGlassTokens {")
            )
        ]
        fields = re.findall(r"^\s*float (\w+)(?:\[4\])?;", struct_body, re.M)
        assert fields == STRUCT_FIELDS, f"the struct reordered: {fields}"


class TestTheCapsuleIsACapsule:
    def test_the_pill_radius_is_the_palette_capsule_value(self) -> None:
        """The pill is a capsule at every height, so its radius is not a length.

        `999` is `MX_R_PILL` in `interface_mixar_palette.hh`: the painter clamps
        a radius to half the short side, which is the capsule rule, so one
        number covers a 38px pill and a 24px badge alike.
        """
        pill = _rows()["pill"]
        radius = re.search(r"/\*\s*radius\s*\*/\s*([0-9.]+)f", pill)
        assert radius is not None, "the pill row has no radius"
        assert float(radius.group(1)) >= 999.0, (
            "A finite pill radius is a rounded rectangle on some pill heights and "
            "a capsule on others: the same window would change shape as it resizes."
        )
        assert "MX_R_PILL" in TOKENS and "capsule" in TOKENS

    def test_the_painter_clamps_every_radius_to_half_the_short_side(self) -> None:
        assert "std::min(width, height) * 0.5f" in DRAW, (
            "Without the clamp the pill's 999 draws a shape that is not a pill at all."
        )

    def test_the_pill_row_owns_the_resting_rim(self) -> None:
        """The white 0.14 stroke the elongated pill used to paint on itself.

        The rim has to stay concentric with the pane, so it is drawn once, by
        the kit: when the call site painted it too the two alphas stacked to
        0.26 and the pill read noticeably brighter than its artboard. The PILL
        row therefore keeps the stroke the call site gave up.
        """
        rim = re.search(r"/\*\s*rim\s*\*/\s*\{([^}]*)\}", _rows()["pill"])
        assert rim is not None, "the pill row has no rim"
        parts = [p.strip() for p in rim.group(1).split(",")]
        assert parts[:3] == ["1.000f", "1.000f", "1.000f"], (
            f"the pill's resting rim stopped being a white stroke: {parts}"
        )
        assert parts[3] in ("0.14f", "0.140f"), (
            f"the resting rim's alpha drifted from the artboard's 0.14: {parts}"
        )


class TestTheSpecularIsDeterministicAndInDegrees:
    def test_the_streak_is_time_driven_and_never_random(self) -> None:
        """Two panes side by side must sweep together, and a still must repeat.

        A random phase would desynchronise a card and its pill -- the pair reads
        as one surface -- and make every screenshot different.
        """
        assert not re.search(r"\b(?:std::)?(?:rand|srand|random)\s*\(", _code(KIT + DRAW)), (
            "The specular streak is time-driven; a random source would break "
            "side-by-side panes and reproducibility."
        )
        assert "BLI_rng" not in _code(KIT + DRAW)
        assert "std::fmod(BLI_time_now_seconds() / double(t.specular_period), 1.0)" in DRAW

    def test_the_tilt_is_passed_as_degrees_because_the_api_wants_degrees(self) -> None:
        """`GPU_matrix_rotate_2d` takes DEGREES, whatever the constant is called.

        Its call sites convert before calling it (`wm_operators.cc` wraps its own
        radians in `RAD2DEGF`), so a constant documented in radians and passed
        through would lean the streak by 0.4 instead of 22 degrees -- which looks
        like no lean at all, not like a bug.
        """
        tilt = re.search(r"constexpr float ([A-Z_]+_DEG) = ([0-9.]+)f;", DRAW)
        assert tilt is not None, "the tilt constant is not named as degrees"
        assert float(tilt.group(2)) > 1.0, (
            "A sub-degree value passed to a degrees API reads as no lean; a lean "
            "expressed in radians is the bug this pins."
        )
        assert "DEGREES" in DRAW
        assert "GPU_matrix_rotate_2d(GLASS_SPECULAR_TILT_DEG)" in DRAW
        assert "RAD2DEG" not in _code(DRAW) and "DEG2RAD" not in _code(DRAW), (
            "A conversion here would double-convert: the API already takes degrees."
        )


class TestTheSpecularIsClippedToTheRegion:
    def test_the_scissor_origin_is_never_negative(self) -> None:
        """A pane may hang off the region; a negative scissor origin is invalid.

        The card straddles the viewport's edge mid-drag, which is exactly when
        the streak is drawn.
        """
        assert "std::max(rect.xmin + int(inset), 0)" in DRAW
        assert "std::max(rect.ymin + int(inset), 0)" in DRAW

    def test_the_scissor_is_restored_after_the_streak(self) -> None:
        assert "GPU_scissor_get(scissor_prev);" in DRAW
        assert "GPU_scissor(scissor_prev[0], scissor_prev[1], scissor_prev[2], scissor_prev[3]);" in DRAW


class TestTheBlurIsARealCascade:
    def test_the_chain_halves_and_then_walks_back_up(self) -> None:
        """Down alone is a grid of 2x2 blocks; the walk back is what smooths it.

        A bilinear resize to half size IS a 2x2 box average, so the downsample
        is the blur; without the upsample the result is visibly blocky, which
        reads as a scaling bug rather than as a blur.
        """
        assert "constexpr int GLASS_BLUR_LEVELS = 4;" in KIT
        assert "std::max(1, w >> i)" in KIT and "std::max(1, h >> i)" in KIT
        assert "for (int i = 1; i < g_chain.level_count; i++) {" in KIT
        assert "for (int i = g_chain.level_count - 1; i > 0; i--) {" in KIT

    def test_the_level_count_follows_the_radius(self) -> None:
        assert re.search(
            r"std::clamp\(1 \+ int\(std::log2\(std::max\(blur_radius, 1\.0f\)\)\),\s*2,\s*GLASS_BLUR_LEVELS\)",
            KIT,
        ), "A fixed level count cannot serve an 8px chip and a 24px panel alike."

    def test_every_cascade_pass_replaces_rather_than_blends(self) -> None:
        """A blur stage that blended toward its input would be a blend, not a blur.

        `GPU_SHADER_3D_IMAGE` carries no colour to weight the sample with, and
        alpha-blending a level onto an opaque destination can only DESTROY
        alpha, so each pass must overwrite its target wholesale.
        """
        assert KIT.count("glass_blit_full(") == 4, "one definition and three passes"
        assert _code(KIT).count("GPU_BLEND_NONE") == 3, (
            "Every cascade pass must be replace-mode; a blended pass silently "
            "stops being a blur."
        )


class TestTheChainIsFreedAndReused:
    def test_every_level_is_released(self) -> None:
        assert KIT.count("GPU_offscreen_create(") == 1
        assert "GPU_offscreen_free(g_chain.levels[i]);" in KIT
        assert "g_chain.levels[i] = nullptr;" in KIT

    def test_a_resize_releases_before_it_reallocates_and_gives_up_cleanly(self) -> None:
        ensure = KIT[
            KIT.index("bool glass_chain_ensure(") : KIT.index(
                "void glass_blit_full(", KIT.index("bool glass_chain_ensure(")
            )
        ]
        assert ensure.index("glass_chain_release();") < ensure.index("GPU_offscreen_create(")
        failure = ensure[ensure.index("if (g_chain.levels[i] == nullptr)") :]
        assert "glass_chain_release();" in failure and "return false;" in failure, (
            "A half-built chain must be released, or the next ensure reuses "
            "surfaces that were never created."
        )

    def test_the_chain_can_be_released_from_outside(self) -> None:
        assert re.search(r"void mixar_glass_free\([^)]*\)\s*\{\s*\n\s*glass_chain_release\(\);", KIT)


class TestTheBackdropIsNeverInvented:
    def test_an_empty_source_returns_an_empty_backdrop_before_allocating(self) -> None:
        prepare = KIT[KIT.index("MixarGlassBackdrop mixar_glass_backdrop_prepare(") :]
        prepare = prepare[: prepare.index("\n}\n")] if "\n}\n" in prepare else prepare
        assert "if (!source.valid()) {" in prepare
        assert prepare.index("if (!source.valid())") < prepare.index("glass_chain_ensure("), (
            "An empty source is an ordinary input, not a failure to allocate for."
        )

    def test_the_kit_never_creates_a_texture_of_its_own(self) -> None:
        assert "GPU_texture_create" not in KIT, (
            "The kit blurs what it is handed; a texture it made itself would be "
            "a backdrop it did not have."
        )

    def test_the_painter_draws_the_bed_only_for_a_valid_backdrop(self) -> None:
        assert "if (backdrop.valid()) {" in DRAW


class TestThePaneFadesAsOneWhole:
    def test_every_layer_is_multiplied_by_the_pane_alpha(self) -> None:
        """`alpha` is the reveal: a layer that ignores it stays on screen.

        That is the "stuck pill" report -- a pane the app has dismissed but the
        screen still shows.
        """
        for scaled in (
            "t.tint_top[3] * alpha",
            "t.tint_bottom[3] * alpha",
            "t.glaze[3] * alpha",
            "t.sheen[3] * alpha",
            "t.rim[3] * alpha",
            "t.shadow[3] * alpha",
            "t.specular_alpha * alpha",
        ):
            assert scaled in DRAW, f"{scaled} is missing, so that layer never fades"

    def test_the_refraction_and_the_bed_are_faded_too(self) -> None:
        assert "glass_draw_refraction(&inside, t.refract, alpha);" in DRAW
        assert "glass_draw_texture_window(backdrop.texture, &bed, &backdrop.rect, alpha);" in DRAW

    def test_the_bed_uses_the_colour_carrying_shader_so_it_can_fade(self) -> None:
        """`GPU_SHADER_3D_IMAGE` has no colour uniform: the sample cannot be weighted.

        A bed drawn with it can only appear at full strength, so the backdrop
        pops in at the end of the reveal instead of fading with the tint. The
        colour variant carries the uniform (`wm_operators.cc` binds it the same
        way), so the bed fades with everything else.
        """
        assert "immBindBuiltinProgram(GPU_SHADER_3D_IMAGE_COLOR);" in DRAW
        assert "immUniformColor3fvAlpha(white, alpha);" in DRAW
        assert "immBindTexture(\"image\", tex);" in DRAW
        assert "GPU_SHADER_3D_IMAGE)" not in DRAW, (
            "The replace-only shader belongs in the cascade; on the bed it would "
            "make the backdrop un-fadeable."
        )

    def test_the_header_documents_alpha_as_applying_to_every_layer(self) -> None:
        assert "every layer" in HEADER


class TestTheBedStaysInsideTheSilhouette:
    def test_the_bed_is_inset_past_the_rounded_corner(self) -> None:
        """A rounded corner departs from its square by at most 0.293 * radius.

        The bed is a rectangle and the pane is not, so an inset smaller than
        that would push the bed's corners outside the shape it sits in -- which
        cannot be seen, because the pane's own tint is already under it and the
        corner that leaks is a few pixels of someone else's backdrop.
        """
        assert "std::min(radius * 0.5f, std::min(float(width), float(height)) * 0.25f)" in DRAW

    def test_the_texture_is_bound_to_the_inset_bed_not_the_silhouette(self) -> None:
        assert "glass_draw_texture_window(backdrop.texture, &bed," in DRAW
        assert "draw_roundbox_4fv_ex(&box, tint_top, tint_bottom, 1.0f, nullptr, 0.0f, radius);" in DRAW


class TestTheWindowRequestIsPlatformSafe:
    def test_the_call_sits_inside_the_platform_guard(self) -> None:
        """`Mixar_WindowSetBlurBehind` is defined only by Cocoa and Win32 GHOST.

        Calling it outside the guard is an undefined reference on Linux, so the
        guarded *definition* in the kit is the only form that links on all
        three platforms.
        """
        assert _lines_outside_window_guard(KIT, ["Mixar_WindowSetBlurBehind"]) == []
        assert KIT.count("Mixar_WindowSetBlurBehind") == 2, "one declaration, one call"

    def test_the_kit_does_not_redefine_the_ghost_symbol(self) -> None:
        assert re.search(
            r'extern "C" void Mixar_WindowSetBlurBehind\(void \*window_handle, bool enable\);', KIT
        ), "It must be declared with C linkage, or the guarded call links against nothing."

    def test_the_other_platforms_report_that_nothing_was_done(self) -> None:
        assert KIT.count("#else") == 1
        alt = KIT[KIT.index("#else") : KIT.index("#endif", KIT.index("#else"))]
        assert "return false;" in alt and "(void)ghostwin;" in alt, (
            "The no-op must say so, so a caller can tell that the window stayed opaque."
        )

    def test_callers_need_no_guard_of_their_own(self) -> None:
        assert not re.search(r"^\s*#\s*(?:if|ifdef|ifndef)", HEADER, re.M), (
            "A conditional public API forces every call site to repeat the guard."
        )
        assert "bool mixar_glass_window_apply_translucency(void *ghostwin, const bool enable)" in KIT
        assert "Mixar_WindowSetBlurBehind" not in _code(HEADER), (
            "The header names the platform call in prose, but must never reach for it."
        )
        assert "Mixar_WindowSetBlurBehind" not in _code(DRAW)


class TestThePainterRestoresTheStateItTouches:
    def test_every_matrix_push_is_matched(self) -> None:
        for name, src in (("kit", KIT), ("painter", DRAW)):
            assert len(re.findall(r"GPU_matrix_push\(\)", src)) == len(
                re.findall(r"GPU_matrix_pop\(\)", src)
            ), f"unbalanced matrix push/pop in the {name}"
            assert len(re.findall(r"GPU_matrix_push_projection\(\)", src)) == len(
                re.findall(r"GPU_matrix_pop_projection\(\)", src)
            ), f"unbalanced projection push/pop in the {name}"

    def test_the_blend_mode_is_saved_and_restored(self) -> None:
        for name, src in (("kit", KIT), ("painter", DRAW)):
            assert "GPU_blend_get()" in src, f"the {name} changes blend without reading it"
            assert "GPU_blend(blend_prev);" in src, f"the {name} does not restore blend"

    def test_a_pane_can_be_drawn_mid_pass(self) -> None:
        """The painter pushes its own state, so callers need not wrap it."""
        assert "GPU_matrix_push_projection();" in DRAW
        assert "GPU_matrix_pop_projection();" in DRAW


class TestThePublicApiIsDefinedOnce:
    def test_every_declared_symbol_has_exactly_one_definition(self) -> None:
        for name in PUBLIC_API:
            assert f"{name}(" in HEADER, f"{name} is not declared"
            matches = re.findall(
                rf"^[A-Za-z_][\w:<>\* ]*\s{re.escape(name)}\(", KIT + TOKENS + DRAW, re.M
            )
            assert len(matches) == 1, f"{name} has {len(matches)} definitions, not one"

    def test_the_kit_splits_along_the_material_seam(self) -> None:
        """`foo.cc` + `foo_draw.cc` + `foo_tokens.cc`, like the cinema row.

        The material table is prose-heavy (a row per surface, each carrying the
        call-site colour it stands in for) and holds no GPU calls, so it is the
        one seam that can come out whole — which is what keeps each file under
        the repo's size limit as surfaces are added.
        """
        assert "MixarGlassTokens mixar_glass_tokens(" in TOKENS
        assert "MixarGlassTokens g_glass_tokens" in TOKENS
        assert "void mixar_glass_draw(" in DRAW
        assert "MixarGlassTokens g_glass_tokens" not in KIT
        assert "MixarGlassTokens g_glass_tokens" not in DRAW


class TestTheFilesStayWithinTheHouseLimits:
    def test_no_file_is_larger_than_the_house_limit(self) -> None:
        """`CLAUDE.md`: "No file larger than 500 lines -- split aggressively."

        The kit was 710 lines as one file, which forced the split along the
        `_draw` seam; the material table then grew it past the limit again,
        which forced the `_tokens` seam. Every file in the family is checked,
        so the next surface is added by growing a file that still has room.
        """
        for path in (KIT_PATH, TOKENS_PATH, DRAW_PATH):
            count = len(path.read_text(encoding="utf-8").splitlines())
            assert count < 500, f"{path.name} is {count} lines"

    def test_every_part_is_in_the_build(self) -> None:
        for name in (
            "interface_mixar_liquid_glass.cc",
            "interface_mixar_liquid_glass_tokens.cc",
            "interface_mixar_liquid_glass_draw.cc",
        ):
            assert f"  {name}\n" in CMAKE, f"{name} is not compiled"
        assert CMAKE.index("interface_mixar_liquid_glass.cc") < CMAKE.index(
            "interface_mixar_liquid_glass_draw.cc"
        ) < CMAKE.index("interface_mixar_liquid_glass_tokens.cc") < CMAKE.index(
            "interface_mixar_profile_card.cc"
        )
