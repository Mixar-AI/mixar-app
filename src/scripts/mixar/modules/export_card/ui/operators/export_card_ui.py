# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Export card — frame, header, the tile sidebar and the right column.

The same native sheet as AI Provider settings (`common/sheet/kit`), wider:
a sidebar of app-icon tiles grouped PROJECT / 3D MODEL / MEDIA & WEB
(`common/sheet/tiles`), and a right column whose rows come from
`export_card_forms` (the target's settings) over `export_card_foot` (the
destination and the one Export button, or the state's recap). Each part is
planned as `Rows` — heights first, then drawing — so both columns end on the
same line and the foot always sits at the card's bottom.

The one-action contract: every state marks exactly ONE button as the
dialog's active default, which keeps the props dialog's OK/Cancel row away;
the ✕ and Done are cancel-path dismisses. This module only draws."""

from mixar.modules.common.i18n import iface_
from mixar.modules.common.sheet import kit as S
from mixar.modules.common.sheet import tiles as T

from dataclasses import dataclass

from ... import constants as C
from ...core import logos, state, targets


@dataclass(frozen=True)
class Metrics:
    """One size of the card (design px, 2x). REGULAR is wider than the
    provider sheet so the sidebar holds three full tiles per line; COMPACT is
    the provider sheet's width with small tiles and tight rows, chosen when
    the window cannot hold REGULAR (`choose_compact`) — a primary action
    must never open off-screen."""
    width: int
    tiles: T.TileSize
    side_inset: int
    group_gap: int
    caption_to_tiles: int
    sidebar_bottom: int
    set_h: int
    row_gap: int
    label_w: int
    name_w: int
    foot_gap: int

    @property
    def sheet_width(self):
        return self.width // 2

    @property
    def sidebar(self):
        return self.side_inset * 2 + T.tiles_width(3, self.tiles)

    @property
    def split_factor(self):
        return (self.sidebar / 2) / (self.width / 2 - S.SPLIT_SPACE / 2)

    @property
    def text_w(self):
        """Room a text line of the right column may use (from the prompt inset)."""
        return self.width - self.sidebar - S.SPLIT_SPACE - S.PROMPT_INSET - S.RIGHT_MARGIN


REGULAR = Metrics(width=1760, tiles=T.REGULAR, side_inset=50, group_gap=20,
                  caption_to_tiles=10, sidebar_bottom=30, set_h=44, row_gap=10,
                  label_w=250, name_w=470, foot_gap=22)
COMPACT = Metrics(width=1440, tiles=T.COMPACT, side_inset=34, group_gap=10,
                  caption_to_tiles=4, sidebar_bottom=16, set_h=40, row_gap=4,
                  label_w=230, name_w=330, foot_gap=10)
# Room kept free around the card when choosing its size (design px).
WINDOW_MARGIN = 120
# REGULAR's tallest common body (glTF with the sidebar's four tile rows) plus
# the header: below this window height the card opens COMPACT.
REGULAR_HEIGHT = 1200
# Kept for callers that size the dialog before it opens.
SHEET_WIDTH = REGULAR.sheet_width
TEXT_W = REGULAR.text_w


def metrics():
    return COMPACT if state.compact() else REGULAR


def choose_compact(window, ui_scale):
    """Whether REGULAR would not fit ``window`` (region px at ``ui_scale``:
    one design px is ``ui_scale / 2`` window px)."""
    if window is None or not ui_scale:
        return False
    width_dp = window.width * 2.0 / ui_scale
    height_dp = window.height * 2.0 / ui_scale
    return (width_dp < REGULAR.width + WINDOW_MARGIN
            or height_dp < REGULAR_HEIGHT + WINDOW_MARGIN)


class Rows:
    """A column planned before it is drawn: ``(height, draw)`` entries, a
    ``None`` draw being a spacer. ``draw(col)`` adds exactly ``height`` dp."""

    def __init__(self):
        self.items = []

    def add(self, height, draw):
        self.items.append((height, draw))

    def gap(self, height):
        if height > 0:
            self.items.append((height, None))

    @property
    def height(self):
        return sum(height for height, _draw in self.items)

    def build(self, col):
        for height, draw in self.items:
            if draw is None:
                S.sep(col, height)
            else:
                draw(col)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def draw_dialog(layout, context):
    """`mixar.export_card`'s draw()."""
    from . import export_card_foot, export_card_forms

    layout.use_property_split = False
    layout.use_property_decorate = False
    p = context.window_manager.mixar_export_card
    busy = p.state == C.RUNNING
    m = metrics()

    sheet = layout.column(align=True)
    if hasattr(sheet, 'mixar_sheet_frame'):
        sheet.mixar_sheet_frame(header=S.HEADER, sidebar=m.sidebar)
    _draw_header(sheet, busy)

    form = export_card_forms.plan(sheet, context, p)
    foot = export_card_foot.plan(sheet, context, p)
    side = sidebar_rows(p, enabled=not busy)
    body_h = max(side.height, form.height + foot.height + S.GAP)

    body = sheet.split(factor=m.split_factor, align=True)
    left = S.fixed(body.column(align=True), body_h)
    side.build(left)
    right = S.fixed(body.column(align=True), body_h)
    top = S.fixed(right, body_h - foot.height)
    top.enabled = p.state in (C.IDLE, 'CONFIRM') or (p.target == C.WEB and not busy)
    form.build(top)
    foot.build(right)


def _draw_header(sheet, busy):
    header = sheet.row(align=True)
    title = header.row(align=True)
    title.scale_y = S.units(S.HEADER)
    S.label(title,
            iface_("Export") + "\n"
            + iface_("Save your scene as a project, a 3D file, an image or video, "
                     "or a page on the web."),
            S.TITLE, translate=False)
    if busy:
        # An export in flight keeps the card until it lands.
        return
    slot = S.sized(header, S.CLOSE)
    slot.scale_y = S.units(S.CLOSE_TOP + S.CLOSE)
    S.dismiss(slot, S.CLOSE_GLYPH, S.CLOSE_KIND)
    S.gap(header, S.CLOSE_RIGHT)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def sidebar_rows(p, enabled=True):
    m = metrics()
    rows = Rows()
    for index, group in enumerate(targets.GROUPS):
        rows.gap((S.CAPTION_TOP if m is REGULAR else S.CAPTION_TOP // 2) if index == 0
                 else m.group_gap)
        rows.add(S.CAPTION_H, lambda col, g=group: S.label(
            S.row(col, S.CAPTION_H, left=m.side_inset), g, S.CAPTION))
        rows.gap(m.caption_to_tiles)
        members = targets.in_group(group)
        items = [(C.OP_PICK, t.tile, t.id == p.target, logos.icon_id(t.logo), {"target": t.id})
                 for t in members]
        n_rows = (len(items) + 2) // 3

        def draw(col, items=items, enabled=enabled):
            grid = col.column(align=True)
            grid.enabled = enabled
            T.tile_grid(grid, items, 3, m.side_inset, m.tiles)

        rows.add(T.tile_rows_height(n_rows, m.tiles), draw)
    rows.gap(m.sidebar_bottom)
    return rows


# Auto-discovery imports every file under ui/ — nothing to register here.
classes = ()
