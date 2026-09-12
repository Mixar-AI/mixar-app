# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Agent pill's window must BE the capsule, not a box containing one.

``Mixar_WindowSetCornerRadius`` is one contract with two implementations.
macOS honours it as a Core Animation mask -- ``layer.cornerRadius`` plus
``masksToBounds`` over a non-opaque window -- so everything outside the radius
is genuinely transparent and the resting pill is all the user sees.

Windows has no equivalent for a GL-rendered window. ``GHOST_WindowWin32``
constructs ``GHOST_ContextWGL`` with ``alphaBackground=false``, so the client
area carries no alpha channel and DWM composites it as opaque whatever the
shader writes. The pill paints an opaque near-black bed over its whole region
(deliberately -- it is what stops the capsule blinking when the cached region
buffer is stale), and that bed showed as a hard black rectangle around the
capsule wherever the viewport behind it was not equally dark. A Windows 11
border line traced the same rectangle on top.

So the Win32 half owes two things the naive port did not have: no OS border,
and the radius applied as the window's actual SHAPE. Both are pinned here,
along with the two ways a window region silently goes wrong -- a resize that
leaves a stale region clipping live content, and an entry outliving its HWND.

The island asks the same question one level up: its window can be given a
translucent background, and only then do the beds it paints per region have
anything to reveal. That contract is pinned here too, beside the pill's,
because it is the same question put to a different window.

Source-level, because none of it is reachable from Python.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WIN32 = ROOT / "src" / "intern" / "ghost" / "intern" / "GHOST_SystemWin32.cc"
WIN32_GLASS = ROOT / "src" / "intern" / "ghost" / "intern" / "GHOST_MixarGlassWin32.cc"
GHOST_CMAKE = ROOT / "src" / "intern" / "ghost" / "CMakeLists.txt"
COCOA = ROOT / "src" / "intern" / "ghost" / "intern" / "GHOST_SystemCocoa.mm"
COCOA_GLASS = ROOT / "src" / "intern" / "ghost" / "intern" / "GHOST_MixarGlassCocoa.mm"
EDITOR = ROOT / "src" / "source" / "blender" / "editors" / "space_agent_bubble"
PILL_DRAW = EDITOR / "agent_ui_draw.cc"
SPACE = EDITOR / "space_agent_bubble.cc"
GLASS = EDITOR / "agent_bubble_glass.cc"


def _read(path: Path) -> str:
    assert path.is_file(), f"missing overlay source: {path}"
    return path.read_text(encoding="utf-8")


def _fn_body(src: str, signature: str) -> str:
    """The text of one top-level function, from its signature to column-0 '}'."""
    start = src.index(signature)
    end = src.index("\n}\n", start)
    return src[start:end]


@pytest.fixture(scope="module")
def win32() -> str:
    return _read(WIN32)


class TestWin32WindowIsShaped:
    """The radius must reach the window, not just DWM's preference."""

    def test_corner_radius_applies_a_window_region(self, win32: str) -> None:
        body = _fn_body(win32, 'extern "C" void Mixar_WindowSetCornerRadius(')
        assert "s_corner_shapes" in body, (
            "Mixar_WindowSetCornerRadius must record the requested radius so the "
            "region can be rebuilt on later resizes."
        )
        assert "mixar_window_apply_corner_region" in body, (
            "The radius must be applied as the window's shape. Without it the "
            "pill's opaque bed fills the window RECTANGLE and reads as a black "
            "box around the capsule."
        )

    def test_region_is_a_round_rect_owned_by_the_window(self, win32: str) -> None:
        body = _fn_body(win32, "static void mixar_window_apply_corner_region(")
        assert "CreateRoundRectRgn" in body
        assert "SetWindowRgn" in body
        # SetWindowRgn takes ownership; deleting the region after handing it over
        # is a use-after-free that Windows reports as nothing at all.
        assert "DeleteObject" not in body, (
            "SetWindowRgn takes ownership of the HRGN -- it must not be deleted."
        )

    def test_dwm_rounding_is_declined_in_favour_of_our_own(self, win32: str) -> None:
        body = _fn_body(win32, 'extern "C" void Mixar_WindowSetCornerRadius(')
        assert "DWMWCP_DONOTROUND;" in body, (
            "DWM's corner preference only offers its own ~8px radius. On the "
            "pill (28.5px) that drew a near-square outline around a capsule, so "
            "the shape has to be ours alone."
        )

    def test_windows_11_border_is_removed(self, win32: str) -> None:
        helper = _fn_body(win32, "static void mixar_window_remove_dwm_border(")
        assert "0xFFFFFFFE" in helper, "DWMWA_COLOR_NONE"
        assert "34" in helper, "DWMWA_BORDER_COLOR"
        # Every window that loses its frame must also lose the OS border line.
        for signature in (
            'extern "C" void Mixar_WindowSetChromeless(',
            'extern "C" void Mixar_WindowSetBorderless(',
            'extern "C" void Mixar_WindowSetCornerRadius(',
        ):
            assert "mixar_window_remove_dwm_border" in _fn_body(win32, signature), signature


class TestWin32RegionStaysCorrect:
    """A window region is a snapshot of a size. Both ways it goes stale."""

    def test_region_is_rebuilt_on_every_resize(self, win32: str) -> None:
        body = _fn_body(win32, "static LRESULT CALLBACK mixar_min_size_subclass_proc(")
        assert "WM_WINDOWPOSCHANGED" in body and "mixar_window_apply_corner_region" in body, (
            "Mixar_WindowForceSize is called from paths that do not follow with "
            "another SetCornerRadius (the island's own sizing, the Scribble "
            "pad). Without a rebuild on resize, a stale region clips live "
            "content and there is no error anywhere."
        )

    def test_rebuild_is_a_no_op_when_the_size_is_unchanged(self, win32: str) -> None:
        body = _fn_body(win32, "static void mixar_window_apply_corner_region(")
        assert "applied_w" in body and "applied_h" in body, (
            "SetWindowRgn redraws, which can produce another WM_WINDOWPOSCHANGED "
            "-- the size guard is what stops that being a loop."
        )

    def test_shape_is_forgotten_with_its_window(self, win32: str) -> None:
        body = _fn_body(win32, "static LRESULT CALLBACK mixar_min_size_subclass_proc(")
        destroy = body[body.index("WM_NCDESTROY") :]
        assert "s_corner_shapes.erase(hwnd)" in destroy, (
            "HWNDs are reused; a stale entry would shape an unrelated window."
        )


class TestWin32PerPixelAlpha:
    """Where DWM will composite the client alpha, that IS the shape.

    A window region is binary coverage: the 28.5px capsule it rasterises has
    the hard staircase of any un-anti-aliased circle. Asking DWM to honour the
    alpha channel gives the capsule's own feathered edge instead -- but only
    where the pixel format GHOST actually got carries alpha bits, which nothing
    requested and which therefore has to be READ rather than assumed.
    """

    def test_alpha_is_probed_not_assumed(self, win32: str) -> None:
        probe = _fn_body(win32, 'extern "C" bool Mixar_WindowHasAlphaChannel(')
        assert "DescribePixelFormat" in probe and "cAlphaBits" in probe, (
            "GHOST_WindowWin32 constructs GHOST_ContextWGL with "
            "alphaBackground=false, so this must read the format that was "
            "chosen, not the one that was asked for."
        )
        enable = _fn_body(win32, 'extern "C" void Mixar_WindowSetPerPixelAlpha(')
        assert "Mixar_WindowHasAlphaChannel" in enable, (
            "Enabling without the channel leaves the corners composited opaque "
            "-- the black box, back again, with no region to fall back on."
        )

    def test_native_frost_keeps_the_window_shape(self, win32: str) -> None:
        body = _fn_body(win32, "static void mixar_window_apply_corner_region(")
        head = body[: body.index("s_corner_shapes.find")]
        assert "SetWindowRgn(hwnd, NULL" not in head
        assert "s_per_pixel_alpha_windows" not in win32

    def test_the_two_are_mutually_exclusive_by_construction(self, win32: str) -> None:
        enable = _fn_body(win32, 'extern "C" void Mixar_WindowSetPerPixelAlpha(')
        assert "mixar_window_apply_corner_region" in enable, (
            "Toggling alpha has to re-run the shape decision, or a region set "
            "earlier in the window's life keeps clipping."
        )


class TestWin32LiquidGlass:
    """Per-pixel alpha is not frost. The 1×1 blur region only opted DWM
    into looking at alpha; the material has to be Acrylic (or a full-window
    blur on older builds) and DWM has to honour the GPU's wash.
    """

    def test_blur_behind_installs_win32_glass(self, win32: str) -> None:
        body = _fn_body(
            win32, 'extern "C" bool Mixar_WindowSetBlurBehind(void *window_handle, bool enable)\n{'
        )
        assert "Mixar_Win32GlassSetEnabled" in body
        assert "CreateRectRgn(0, 0, 1, 1)" not in body, (
            "A 1×1 blur region is the old alpha-only trick — not glass."
        )

    def test_acrylic_is_the_material_not_mica(self) -> None:
        glass = _read(WIN32_GLASS)
        assert "Mixar_Win32GlassSetEnabled" in glass
        assert "kDwmwaSystemBackdropType = 38" in glass
        assert "kDwmsbtTransientWindow = 3" in glass
        assert "kDwmsbtNone = 1" in glass
        assert "kDwmwaRedirectionBitmapAlpha = 39" in glass
        assert "kDwmwaUseImmersiveDarkMode = 20" in glass
        assert "DwmExtendFrameIntoClientArea" in glass
        assert "DWM_BB_ENABLE" in glass
        assert "DWM_BLURBEHIND bb = {};" in glass
        assert "FAILED(material)" in glass
        assert "mixar_disable_glass(hwnd);" in glass
        assert "CreateRectRgn(0, 0, 1, 1)" not in glass
        assert "DWMSBT_MAINWINDOW" not in glass
        cmake = _read(GHOST_CMAKE)
        assert "intern/GHOST_MixarGlassWin32.cc" in cmake
        assert "intern/GHOST_MixarGlassWin32.hh" in cmake


class TestCrossPlatformContract:
    """The same call means the same thing on both platforms."""

    def test_macos_still_masks_to_the_radius(self) -> None:
        body = _fn_body(_read(COCOA), 'extern "C" void Mixar_WindowSetCornerRadius(')
        assert "masksToBounds" in body and "cornerRadius" in body
        assert "clearColor" in body, (
            "The mask only reads as a shape because the window is non-opaque."
        )

    def test_the_pill_still_paints_every_pixel_of_its_bed(self) -> None:
        """Neither fix was allowed to be "stop painting the bed".

        The bed exists because the pill's cached region buffer is freed on
        perceived resizes and only repainted on the next tagged redraw; in that
        gap a composite blitted nothing and the pill flashed the bare backdrop.
        Shaping the window hides the bed and per-pixel alpha makes it invisible
        -- neither stops it covering the region, and BLEND_NONE is what writes
        the alpha straight through rather than blending over stale content.
        """
        for src, fn in (
            (_read(PILL_DRAW), "void agent_ui_draw_status_pill("),
            (_read(SPACE), "void agent_bubble_header_region_draw("),
        ):
            body = _fn_body(src, fn)
            assert "agent_bubble_pill_bed_is_transparent()" in body, fn
            assert "GPU_BLEND_NONE" in body, fn
            assert "0.02f" in body, fn
            assert "agent_bubble_replace_frost_wash" in body, fn
            assert "AGENT_COL_GLASS_WASH" in body, fn

    def test_the_pill_bed_requires_confirmed_frost(self) -> None:
        body = _fn_body(_read(GLASS), "bool agent_bubble_pill_bed_is_transparent(")
        assert "return pill_glass.transparent;" in body
        assert "return true;" not in body

    def test_frost_skips_the_dest_over_pill_capsule(self) -> None:
        """glass_fill_round dest-overs; on frost that is the slab."""
        body = _fn_body(_read(PILL_DRAW), "void agent_ui_draw_status_pill(")
        assert "if (agent_bubble_pill_bed_is_transparent())" in body
        assert "agent_bubble_replace_frost_wash(&pill, wash);" in body
        assert "glass_fill_round(&pill, ui::MIXAR_GLASS_PILL, h * 0.5f);" in body

    def test_native_setup_runs_after_creation_outside_paint(self) -> None:
        header = _fn_body(_read(SPACE), "void agent_bubble_header_region_draw(")
        layout = _fn_body(_read(SPACE), "static void agent_bubble_sync_chrome_sizes(const bContext *C)\n{")
        for body in (header, layout):
            assert "glass_request" not in body
            assert "try_per_pixel_alpha" not in body
            assert "try_glass_translucency" not in body
        listener = _fn_body(_read(GLASS), "void agent_bubble_glass_region_listener(")
        assert "NC_WINDOW" in listener
        assert "mixar_glass_window_apply_translucency(window, true)" in listener
        assert "art->listener = agent_bubble_glass_region_listener;" in _read(SPACE)
        footer = _fn_body(_read(SPACE), "static void agent_bubble_footer_region_listener(")
        assert "agent_bubble_glass_region_listener(params);" in footer



class TestIslandWindowTranslucency:
    """The island window asks for the platform's translucent background.

    Where the pill is shaped by DWM honouring its client alpha, the island is
    one window painting several regions, so its route out is the kit's
    ``mixar_glass_window_apply_translucency`` -- a WINDOW background request
    (per-pixel alpha, plus a theme-frame sibling frost on macOS and Desktop
    Acrylic on Windows) and a defined no-op returning false off
    macOS/Windows. The return value is the whole point of calling it rather
    than an ``#ifdef``: it says whether the platform acted.

    The beds then decide what to do with that. They keep covering every pixel
    of every region -- the stale-buffer guarantee the pill's bed exists for is
    the same one -- and only their ALPHA moves: zero where the platform gave
    the window something to show through, one where it did not. The WINDOW
    region's panel fill and the chat bg-override follow the same flag: an
    opaque ``#121212`` slab there hid the frost even when the bed was clear.
    On Linux nothing changes at all.
    """

    def test_the_request_goes_through_the_kit(self) -> None:
        body = _fn_body(_read(GLASS), "void agent_bubble_glass_region_listener(")
        assert "ui::mixar_glass_window_apply_translucency(window, true)" in body
        assert "#if" not in body, "the kit owns the Linux opaque fallback"
        assert "island_glass.apply(ghostwin, apply)" in body

    def test_the_flag_defaults_to_opaque_beds(self) -> None:
        assert "bool transparent = false;" in _read(EDITOR / "agent_bubble_glass.hh")

    def test_island_beds_require_confirmed_frost(self) -> None:
        body = _fn_body(_read(GLASS), "bool agent_bubble_island_bed_is_transparent(")
        assert "return true;" not in body
        assert "return island_glass.transparent;" in body

    def test_the_beds_and_the_panel_read_the_flag(self) -> None:
        src = _read(SPACE)
        assert "agent_bubble_island_panel_color" in src
        helper = _fn_body(src, "static void agent_bubble_island_panel_color(")
        assert "if (agent_bubble_island_bed_is_transparent())" in helper
        assert "AGENT_COL_GLASS_WASH" in helper
        assert "r_rgba[0] = wash[0] * wash[3]" in helper
        assert "r_rgba[3] = wash[3]" in helper
        assert src.count("agent_bubble_island_panel_color(") >= 3, (
            "chat bg-override, empty-state fill and the helper itself"
        )

    def test_the_bed_still_paints_every_pixel_of_its_region(self) -> None:
        """The bed was never allowed to become "don't paint it".

        A dest-over wash cannot lower dest A=1, and an A=0 fragment is a
        no-op on Metal, so the translucent path REPLACES a dark-glass wash.
        The opaque path still fills the rect. Either way every pixel is
        written each frame so a composite in the resize gap cannot show
        the bare backdrop.
        """
        body = _fn_body(_read(SPACE), "static void agent_bubble_fill_region_backdrop(")
        assert "agent_bubble_replace_frost_wash(&r, wash);" in body
        wash = _fn_body(_read(SPACE), "void agent_bubble_replace_frost_wash(")
        assert "rgba[0] * rgba[3]" in wash
        assert "immRectf(pos, rect->xmin, rect->ymin, rect->xmax, rect->ymax)" in wash
        assert "GPU_BLEND_NONE" in body
        assert "ui::draw_roundbox_4fv(&r, true, 0.0f, backdrop);" in body
        assert "GPU_BLEND_NONE" in body, (
            "BLEND_NONE is what writes the bed's alpha straight through."
        )

    def test_the_bed_alpha_follows_the_window(self) -> None:
        body = _fn_body(_read(SPACE), "static void agent_bubble_fill_region_backdrop(")
        assert "agent_bubble_island_bed_is_transparent()" in body
        assert "agent_bubble_replace_frost_wash(&r, wash);" in body
        assert "const float backdrop[4] = {0.0f, 0.0f, 0.0f, 1.0f};" in body

    def test_both_island_styling_sites_ask_for_it(self) -> None:
        """Repair and open are separate paths; neither may be the only one.

        The repair path re-styles any window the dedup reuses, the open path a
        fresh one. Asking in only one of them leaves the other window opaque.
        """
        src = _read(SPACE)
        call = "agent_bubble_glass_request(C, win->runtime->ghostwin, false);"
        radius = "Mixar_WindowSetCornerRadius(win->runtime->ghostwin, AGENT_BUBBLE_CORNER_RADIUS);"
        styled = 0
        pos = 0
        while True:
            i = src.find(call, pos)
            if i < 0:
                break
            if radius in src[max(0, i - 500) : i]:
                styled += 1
            pos = i + 1
        assert styled == 2, (
            f"both island styling sites must call it after the corner radius, found {styled}"
        )
        assert src.count(call) == 2, "only creation and repair queue native setup"

    def test_macos_frost_is_a_theme_frame_sibling_not_a_metal_parent(self) -> None:
        """AppKit frost belongs behind CocoaMetalView, never under it.

        Parenting a frost view under GHOST's Metal surface, or swapping
        ``contentView``, tears the GPU context. The installer adds the
        glass as ``NSWindowBelow`` the host and only marks that window's
        ``CAMetalLayer`` non-opaque.
        """
        cocoa = _read(COCOA)
        body = cocoa[
            cocoa.index("extern \"C\" bool Mixar_WindowSetBlurBehind(") : cocoa.index(
                "extern \"C\" void Mixar_WindowSetChromeless("
            )
        ]
        assert "Mixar_CocoaGlassSetEnabled(win, enable)" in body
        assert "setContentView" not in body
        assert "NSView.tag" not in body

        glass = _read(COCOA_GLASS)
        assert "NSWindowBelow relativeTo:host" in glass
        assert "mixar_give_glass_a_lens" in glass
        assert "MixarGlassLensView" in glass
        assert "setContentView:" in glass
        assert "setContentView:host" not in glass
        assert "[win setContentView" not in glass
        assert "NSView.tag" not in glass and "view.tag" not in glass
        assert "metal.opaque = NO" in glass
        assert "mixar_allow_metal_alpha(win.contentView)" in glass
        assert "Mixar_CocoaGlassAllowMetalAlpha" in glass
        assert "mixar_metal_layer_of" in glass
        assert "wantsExtendedDynamicRangeContent = NO" in glass
        assert "framebufferOnly = NO" in glass
        assert "MTLPixelFormatBGRA8Unorm" in glass
        assert "host.alphaValue = 0.78" not in glass
        assert "CocoaMetalView (MixarTranslucency)" in glass
        assert "return (win == nil) ? YES : win.opaque;" in glass
        assert "NSClassFromString(@\"NSGlassEffectView\")" in glass
        assert "NSVisualEffectView" in glass
        assert 'setStyle:", 0)' in glass, "Regular style — Clear is a hole"
        assert "NSVisualEffectMaterialUnderWindowBackground" in glass
        assert "NSVisualEffectMaterialHUDWindow" not in glass
        assert "colorWithWhite:0.07" not in glass

    def test_metal_present_keeps_framebuffer_alpha(self) -> None:
        """GHOST's present blit used to force alpha 1.0 on every pixel.

        That made the drawable an opaque slab over the frost sibling no
        matter what the GPU wrote. The overlay keeps the sampled alpha.
        """
        mtl = _read(ROOT / "src" / "intern" / "ghost" / "intern" / "GHOST_ContextMTL.mm")
        assert "if (!MIXAR_TRANSLUCENT)" in mtl
        assert "out_tex.rgb = min(out_tex.rgb, 16384.0);" in mtl
        assert "* out_tex.a" not in mtl
        assert "return out_tex;" in mtl
        assert "mixar_new_present_pipeline" in mtl
        assert "metal_layer_.pixelFormat" in mtl
        assert "Mixar_CocoaGlassAllowMetalAlpha(metal_view_)" in mtl
        assert "METAL_FRAMEBUFFERPIXEL_FORMAT_EDR" in mtl

    def test_frost_skips_the_opaque_panel_slab(self) -> None:
        """Empty TOOLS paints the full island. The inner-panel fill was
        opaque ``AGENT_COL_SURFACE``, so frost never reached the compositor.
        """
        draw = _read(PILL_DRAW)
        island = _fn_body(draw, "void agent_ui_draw_island(")
        assert "if (!agent_bubble_island_bed_is_transparent())" in island
        assert "fill_round(&layout->panel, AGENT_PANEL_RADIUS * u, surface);" in island
        assert "glass_fill_round(&layout->card_fill," in island

    def test_empty_field_text_chrome_honours_wash(self) -> None:
        """The empty-state prompt is a full-region Text button.

        widget_box honoured button_color_set; widget_textbut did not, so the
        theme inner stayed an opaque slab over the frost. Name-style chrome
        now reads but->col the same way.
        """
        widgets = _read(
            ROOT / "src" / "source" / "blender" / "editors" / "interface"
            / "interface_widgets.cc"
        )
        assert "widget_textbut_custom" in widgets
        assert "wt.custom = widget_textbut_custom" in widgets
        space = _read(SPACE)
        assert "const uchar wash[4] = {18, 22, 20, 48}" in space
        assert "agent_bubble_replace_frost_wash(&r, wash);" in space
        assert "if (but->col[3] < 128)" in widgets
        assert "BLI_rcti_size_y(rect) > 120" in widgets

    def test_chat_and_pill_share_the_neutral_native_wash(self) -> None:
        theme = _read(PILL_DRAW.parent / "agent_ui_theme.hh")
        assert "AGENT_COL_GLASS_WASH {0.075f, 0.078f, 0.075f, 0.20f}" in theme
        assert _read(SPACE).count("const float wash[4] = AGENT_COL_GLASS_WASH;") == 3
        assert _read(PILL_DRAW).count("const float wash[4] = AGENT_COL_GLASS_WASH;") == 2
