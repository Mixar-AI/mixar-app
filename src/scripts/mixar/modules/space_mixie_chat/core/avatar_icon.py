# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""User avatar icon — gradient circle + account initial for the top bar.

Generates a small antialiased PNG (send-button gradient disc, white
first letter of the logged-in email) with Pillow, then loads it through
``bpy.utils.previews`` — the same icon path ``agent_bubble.core
.pill_icons`` uses, chosen there because previews.load() preserves
alpha on icon-only buttons where raw ``icon_pixels_float`` does not.

Pillow is used (instead of pill_icons' pure-pixel loop) because the
letter glyph needs real font rasterisation. It ships in the embedded
Python (``scripts/python_requirements.txt``), but every entry point
still degrades gracefully: ``get_avatar_icon_id()`` returns 0 on any
failure and the caller falls back to the stock ``USER`` icon.

Icons are generated lazily on first draw and cached per initial, so
login/logout/email changes just resolve a different cache key. A
failed initial is remembered to keep the draw loop from re-attempting
generation every redraw.
"""

from __future__ import annotations

import os
import sys
import tempfile

import bpy
import bpy.utils.previews

from mixar.config.logging_config import get_logger

_logger = get_logger(__name__)

# Rendered at 4x and downsampled for antialiasing; 64 px matches the
# pill_icons assets and is plenty for the ~20 px top-bar draw size.
_ICON_SIZE = 64
_SUPERSAMPLE = 4

# Disc gradient — same as the chat send button. Read live from
# ThemeMixieChat.chat_send_icon_gradient_start/_end (the values the
# C++ icon_source_edit_cb substitutes into submit_arrow.svg); these
# sRGB defaults mirror the Mixar default theme as the fallback.
_GRADIENT_START_DEFAULT = (0, 192, 199)    # #00C0C7
_GRADIENT_END_DEFAULT = (133, 196, 73)     # #85C449
_LETTER_RGBA = (255, 255, 255, 255)

# Per-platform bold-ish font candidates for the initial. First hit wins;
# Pillow >= 10.1's load_default(size=...) is the scalable fallback.
_FONT_CANDIDATES = {
    "darwin": (
        "/System/Library/Fonts/SFNSDisplay.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
    ),
    "win32": (
        "C:\\Windows\\Fonts\\segoeuib.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
    ),
    "linux": (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ),
}

_pcoll = None
# Icon variants (initial + gradient) whose PNG generation failed this
# session — don't retry from the draw loop.
_failed: set[str] = set()


def _theme_gradient() -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """(start_rgb, end_rgb) 0-255 sRGB from the active theme, or the
    Mixar defaults when the theme isn't reachable (e.g. unit tests)."""
    try:
        theme = bpy.context.preferences.themes[0].mixie_chat
        start = tuple(
            round(c * 255) for c in theme.chat_send_icon_gradient_start[:3])
        end = tuple(
            round(c * 255) for c in theme.chat_send_icon_gradient_end[:3])
        return start, end
    except Exception:  # noqa: BLE001 — theme access is best-effort
        return _GRADIENT_START_DEFAULT, _GRADIENT_END_DEFAULT


def _initial_from_email(email: str) -> str:
    for ch in email or "":
        if ch.isalnum():
            return ch.upper()
    return "?"


# ExtraBold weight on the variable-font wght axis.
_EXTRABOLD_WGHT = 800


def _bundled_manrope_path() -> str | None:
    """Path to the bundled Manrope variable font, or None if unresolved.

    Manrope ships in the app's datafiles/fonts dir (same file BLF loads
    as the default UI font), so it's always present in a real build.
    """
    try:
        base = bpy.utils.system_resource('DATAFILES')
    except Exception:  # noqa: BLE001 — not reachable in unit tests
        return None
    if not base:
        return None
    path = os.path.join(base, "fonts", "Manrope.ttf")
    return path if os.path.exists(path) else None


def _set_extrabold(font) -> None:
    """Push a variable font to ExtraBold (wght=800). No-op if the font
    isn't variable or Pillow/FreeType lacks variation support — the
    initial just stays at the font's default weight."""
    try:
        font.set_variation_by_axes([_EXTRABOLD_WGHT])
        return
    except Exception:  # noqa: BLE001 — fall through to name-based lookup
        pass
    try:
        font.set_variation_by_name("ExtraBold")
    except Exception:  # noqa: BLE001 — static font / unsupported build
        pass


def _load_font(px_size: int):
    from PIL import ImageFont

    # Prefer the bundled Manrope at ExtraBold — on-brand with the UI
    # font, guaranteed present, and a genuinely heavy weight for the
    # avatar initial (the system candidates below are the regular
    # weights and only serve as a degraded fallback).
    manrope = _bundled_manrope_path()
    if manrope:
        try:
            font = ImageFont.truetype(manrope, px_size)
            _set_extrabold(font)
            return font
        except Exception:  # noqa: BLE001 — fall back to system fonts
            pass

    for path in _FONT_CANDIDATES.get(sys.platform, ()):  # pragma: no branch
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, px_size)
            except Exception:  # noqa: BLE001 — try the next candidate
                continue
    try:
        return ImageFont.load_default(size=px_size)
    except TypeError:  # Pillow < 10.1 — tiny bitmap font, last resort
        return ImageFont.load_default()


def _write_avatar_png(filepath: str, letter: str, start_rgb, end_rgb) -> bool:
    """Render gradient-disc + letter PNG. True on success."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        _logger.warning("avatar_icon: Pillow unavailable — using fallback icon")
        return False

    try:
        big = _ICON_SIZE * _SUPERSAMPLE

        # Diagonal linear gradient (top-left start → bottom-right end),
        # matching submit_arrow.svg's 0,0→W,H ramp. Bilinear upscale of
        # a 2x2 with averaged off-diagonal corners interpolates to
        # exactly t=(x+y)/2 — a true linear diagonal ramp.
        mid = tuple((s + e) // 2 for s, e in zip(start_rgb, end_rgb))
        seed = Image.new("RGB", (2, 2))
        seed.putdata([tuple(start_rgb), mid, mid, tuple(end_rgb)])
        gradient = seed.resize((big, big), Image.BILINEAR)

        # Disc alpha mask (antialiased edge kept inside the canvas).
        margin = _SUPERSAMPLE
        mask = Image.new("L", (big, big), 0)
        ImageDraw.Draw(mask).ellipse(
            (margin, margin, big - margin, big - margin), fill=255)

        img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        img.paste(gradient, (0, 0), mask)

        font = _load_font(int(big * 0.52))
        # anchor="mm" centres on the glyph's typographic middle, which
        # optically centres capitals/digits inside the disc.
        ImageDraw.Draw(img).text((big / 2, big / 2), letter, font=font,
                                 fill=_LETTER_RGBA, anchor="mm")

        img = img.resize((_ICON_SIZE, _ICON_SIZE), Image.LANCZOS)
        img.save(filepath, "PNG")
        return True
    except Exception as e:  # noqa: BLE001 — never break a draw callback
        _logger.warning("avatar_icon: PNG generation failed (%s): %s",
                        letter, e)
        return False


def get_avatar_icon_id(email: str) -> int:
    """icon_id for the user's initial avatar, or 0 → caller falls back."""
    global _pcoll

    letter = _initial_from_email(email)
    start_rgb, end_rgb = _theme_gradient()
    # Key by initial AND gradient so a theme edit yields a fresh icon
    # instead of a stale cached disc. The "v2" tag invalidates PNGs
    # cached on disk before the ExtraBold initial change so they get
    # regenerated rather than reused at the old regular weight.
    variant = "avatar_v2_%d_%02x%02x%02x_%02x%02x%02x" % (
        ord(letter), *start_rgb, *end_rgb)
    if variant in _failed:
        return 0

    if _pcoll is None:
        _pcoll = bpy.utils.previews.new()

    if variant in _pcoll:
        return _pcoll[variant].icon_id

    try:
        cache_dir = os.path.join(tempfile.gettempdir(), "mixar_avatar_icons")
        os.makedirs(cache_dir, exist_ok=True)
        png_path = os.path.join(cache_dir, variant + ".png")
    except Exception as e:  # noqa: BLE001
        _logger.warning("avatar_icon: tempdir creation failed: %s", e)
        _failed.add(variant)
        return 0

    # Reuse a PNG from earlier in the OS session (same rationale as
    # pill_icons: register/draw re-runs must not redo the work).
    needs_write = True
    try:
        needs_write = os.path.getsize(png_path) <= 0
    except OSError:
        pass
    if needs_write and not _write_avatar_png(png_path, letter,
                                             start_rgb, end_rgb):
        _failed.add(variant)
        return 0

    try:
        preview = _pcoll.load(variant, png_path, "IMAGE")
        # previews.load() is lazy — the PNG is only decoded when
        # something asks for it. We're inside a draw callback here, and
        # an icon drawn before its pixels exist renders blank (and the
        # top bar rarely redraws to fix itself). Touching icon_size /
        # image_size forces a synchronous decode so the icon is valid
        # this very frame. (pill_icons never needed this: it loads at
        # startup, long before first draw.)
        _ = tuple(preview.icon_size) + tuple(preview.image_size)
        if preview.image_size[0] <= 0:
            # Decode produced nothing (corrupt/unreadable PNG) — fall
            # back to the stock icon rather than a blank slot.
            raise RuntimeError("preview decoded to empty image")
    except Exception as e:  # noqa: BLE001
        _logger.warning("avatar_icon: preview load failed (%s): %s", variant, e)
        _failed.add(variant)
        return 0
    return preview.icon_id


def unregister() -> None:
    global _pcoll
    if _pcoll is not None:
        try:
            bpy.utils.previews.remove(_pcoll)
        except Exception:  # noqa: BLE001
            pass
        _pcoll = None
    _failed.clear()
