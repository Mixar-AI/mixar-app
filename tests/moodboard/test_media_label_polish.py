# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Native media-name sizing, placement and UTF-8 truncation contracts."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPACE_MIXIE = ROOT / "src/source/blender/editors/space_mixie"


def _read(path):
    return path.read_text(encoding="utf-8")


def test_selected_media_shows_its_name_not_a_hovering_bubble():
    """The selection used to raise a rounded "Image"/"Video" bubble over the
    canvas — chrome that covered part of the board to repeat what the picture
    already said. The one thing the tile cannot show is WHICH file it is, so
    that slot carries the media's own name instead, as plain small text with no
    background of its own."""
    labels = _read(SPACE_MIXIE / "mixie_draw_moodboard_media_labels.cc")

    assert "image->id.name + 2" in labels
    assert "moodboard_draw_floating_background" not in labels
    assert "uiDefBut" not in labels
    assert '"Video" : "Image"' not in labels
    # Painted text, so it takes no uiBlock at all.
    assert "uiBlock" not in labels
    assert "BLF_draw(" in labels
    # The name is sized WITH the canvas, not pinned to a constant screen size.
    # Pinned, a zoomed-out 111px tile wore a 126px name -- text wider than the
    # picture it labelled. So the point size carries the DPI factor AND the
    # View2D scale.
    assert "MOODBOARD_MEDIA_LABEL_SIZE_PX * UI_SCALE_FAC * view_scale" in labels
    assert "ui::view2d_scale_get_x(v2d)" in labels
    size = re.search(
        r"#define MOODBOARD_MEDIA_LABEL_SIZE_PX (\d+(?:\.\d+)?)f", labels
    )
    assert size, "the point size must stay a named constant"
    assert float(size.group(1)) <= 12.0



def test_a_media_name_never_outgrows_the_tile_it_labels():
    """Scaling by zoom alone is not enough: a tile's width is its OWN canvas
    size times the zoom, so a user-shrunk image at a high zoom would still wear
    an oversized name. The size is fitted to the tile, floored for legibility,
    and dropped outright when the tile is too narrow to carry a readable name
    -- clamping up without the fit is what puts a name wider than its picture
    back on screen."""
    labels = _read(SPACE_MIXIE / "mixie_draw_moodboard_media_labels.cc")

    for macro in (
        "MOODBOARD_MEDIA_LABEL_MIN_PX",
        "MOODBOARD_MEDIA_LABEL_MAX_PX",
    ):
        assert re.search(rf"#define {macro} (\d+(?:\.\d+)?)f", labels), macro
    floor = float(
        re.search(r"#define MOODBOARD_MEDIA_LABEL_MIN_PX (\d+(?:\.\d+)?)f", labels).group(1)
    )
    ceiling = float(
        re.search(r"#define MOODBOARD_MEDIA_LABEL_MAX_PX (\d+(?:\.\d+)?)f", labels).group(1)
    )
    assert 0.0 < floor < ceiling

    # Floor first (a pulled-back canvas keeps its names), then fit to the tile.
    assert "std::clamp(MOODBOARD_MEDIA_LABEL_SIZE_PX * UI_SCALE_FAC * view_scale" in labels
    assert "font_px *= tile_width / text_width;" in labels
    fit_at = labels.index("font_px *= tile_width / text_width;")
    drop_at = labels.index("if (font_px < MOODBOARD_MEDIA_LABEL_MIN_PX * UI_SCALE_FAC) {")
    assert fit_at < drop_at, "the drop test must read the FITTED size, not the clamped one"

    # Spacing rides the font, so the lockup scales as one piece.
    assert "font_px * MOODBOARD_MEDIA_LABEL_GAP_RATIO" in labels
    assert "font_px * MOODBOARD_MEDIA_LABEL_INSET_RATIO" in labels



def test_a_media_name_is_placed_where_its_own_picture_is_actually_visible():
    """Moving a blocked name to the tile's top-left is not enough: a neighbour
    that covers the strip ABOVE a tile usually overlaps the top of the tile as
    well, so the name landed on that other picture regardless. The placement
    walks down a line at a time and takes the first band the tile itself shows.

    Which neighbours count depends on where the strip is, and the two cases are
    not the same: above the tile the name is in the open, so a neighbour painted
    BEFORE this tile still shows through there and must count; inside the tile
    only the neighbours painted after it can cover it."""
    labels = _read(SPACE_MIXIE / "mixie_draw_moodboard_media_labels.cc")

    assert re.search(r"#define MOODBOARD_MEDIA_LABEL_MAX_PROBES (\d+)", labels)
    # One predicate serving both cases, told apart by the `inside` flag.
    assert "auto strip_is_clear = [&](const float x, const float y, const bool inside)" in labels
    assert "if (other == index || (inside && other < index)) {" in labels
    # Above the tile: every other tile is a candidate blocker.
    assert "const bool inside = !strip_is_clear(text_x, text_y, false);" in labels
    # Inside: probe downward for the first band this tile actually shows.
    assert "const float candidate = top - float(step) * line_height;" in labels
    assert "if (strip_is_clear(text_x, candidate, true)) {" in labels
    # Bounded, because this runs on every redraw.
    assert "step < MOODBOARD_MEDIA_LABEL_MAX_PROBES" in labels
    # A fully blanketed tile still gets its name, rather than losing it.
    assert "text_y = top;" in labels
    # The outline only applies to the inside case, and is turned back off.
    assert "BLF_enable(font_id, BLF_SHADOW);" in labels
    assert "BLF_disable(font_id, BLF_SHADOW);" in labels



def test_a_long_media_name_folds_in_the_middle():
    """A generated name is told apart by its tail and its extension as much as
    its head, so an over-long name keeps both ends and elides the middle. The
    offsets come from the UTF-8 helpers, never raw byte counts — a name cut
    mid-character renders as a replacement glyph."""
    labels = _read(SPACE_MIXIE / "mixie_draw_moodboard_media_labels.cc")

    head = int(
        re.search(r"#define MOODBOARD_MEDIA_LABEL_HEAD_CHARS (\d+)", labels).group(1)
    )
    tail = int(
        re.search(r"#define MOODBOARD_MEDIA_LABEL_TAIL_CHARS (\d+)", labels).group(1)
    )
    limit = int(
        re.search(r"#define MOODBOARD_MEDIA_LABEL_MAX_CHARS (\d+)", labels).group(1)
    )
    assert limit == 20
    # The ellipsis has to buy something: the fold must be shorter than the name
    # it replaces, or a 21-character name comes out longer than the original.
    assert head + tail + 3 <= limit + 2
    assert '"%s...%s"' in labels
    assert "BLI_str_utf8_offset_from_index" in labels
    assert "BLI_strlen_utf8_ex" in labels
