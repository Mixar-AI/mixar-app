# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""App-icon tiles and logo chips for sheet dialogs (the Export card).

A tile is one pickable square: a rounded plate carrying a logo (a preview
icon), its label under it, and a focus ring while it is the current choice
(`interface_mixar_sheet_tiles.cc`, kind ``TILE``). A logo chip is a model
chip led by a small logo (`draw_chip`). Both are written in the kit's design
px (`kit.units`) and degrade to stock buttons on a binary without the
painters — the choice still works, it only stops looking like the artboard.
"""

from collections import namedtuple

from . import kit as S

TILE = 'TILE'
# A tile's slot: the plate (with room for its ring) over the label band; the
# painter fits the plate to the slot. Keep TILE_LABEL_H / TILE_RING_OUT equal
# to `tile_label_h` / `tile_ring_out` in interface_mixar_sheet.hh.
TILE_LABEL_H = 40
TILE_RING_OUT = 10
# `chip_icon` + `chip_icon_gap` in interface_mixar_sheet.hh.
CHIP_ICON = 26
CHIP_ICON_GAP = 10


class TileSize(namedtuple("TileSize", "w plate gap_x gap_y")):
    """A tile grid's measures (design px): slot width, plate side, gaps."""

    @property
    def h(self):
        return self.plate + 2 * TILE_RING_OUT + TILE_LABEL_H


REGULAR = TileSize(w=120, plate=100, gap_x=22, gap_y=18)
# Small windows / large UI scales (a 1680 x 1050 window at 225 %).
COMPACT = TileSize(w=92, plate=64, gap_x=12, gap_y=8)
TILE_W, TILE_PLATE, TILE_H = REGULAR.w, REGULAR.plate, REGULAR.h


def tiles_width(columns, size=REGULAR):
    return columns * size.w + max(0, columns - 1) * size.gap_x


def tile_rows_height(rows, size=REGULAR):
    return rows * size.h + max(0, rows - 1) * size.gap_y


def tile(layout, operator_id, text, lit, icon_value=0, size=REGULAR, **choice_props):
    """One tile in a ``size.w``-wide slot of ``layout`` (a row at ``size.h``).
    ``text`` is already translated. Returns the operator properties."""
    slot = S.sized(layout, size.w)
    if not S.available(slot):
        # Stock fallback: an icon button with the label, depressed while lit.
        props = slot.operator(operator_id, text=text, translate=False,
                              icon_value=icon_value, depress=lit)
    else:
        props = slot.operator(operator_id, text=text, translate=False, icon_value=icon_value)
        S.tag(slot, TILE, lit=lit)
    for name, value in choice_props.items():
        if value:
            setattr(props, name, value)
    return props


def tile_grid(parent, items, columns, left, size=REGULAR):
    """``items`` = ``(operator_id, text, lit, icon_value, props_dict)`` laid
    out ``columns`` per line from ``left`` dp; returns the height used."""
    rows = [items[i:i + columns] for i in range(0, len(items), columns)]
    for index, line_items in enumerate(rows):
        if index:
            S.sep(parent, size.gap_y)
        line = S.row(parent, size.h, left=left, packed=True)
        for column, (operator_id, text, lit, icon_value, props) in enumerate(line_items):
            if column:
                S.gap(line, size.gap_x)
            tile(line, operator_id, text, lit, icon_value, size=size, **props)
    return tile_rows_height(len(rows), size)


def chip_width(layout, text, icon_value=0):
    """A chip's slot: its label, padding and, with a logo, the logo and its gap."""
    width = S.text_width(layout, S.CHIP, text) + 2 * S.CHIP_PAD
    return width + (CHIP_ICON + CHIP_ICON_GAP if icon_value else 0)


def logo_chip(layout, operator_id, text, lit, icon_value=0, **choice_props):
    """A chip led by a logo, sized to fit; ``text`` already translated."""
    slot = S.sized(layout, chip_width(layout, text, icon_value))
    if not S.available(slot):
        props = slot.operator(operator_id, text=text, translate=False,
                              icon_value=icon_value, depress=lit)
        for name, value in choice_props.items():
            if value:
                setattr(props, name, value)
        return props
    S.choice(slot, operator_id, text, S.CHIP, lit=lit, icon_value=icon_value, **choice_props)
    return None


def chip_line(parent, items, left, right=0.0):
    """One packed line of logo chips: ``(operator_id, text, lit, icon_value,
    props_dict)``, butted like the kit's model chips."""
    line = S.row(parent, S.CHIP_H, left=left, right=right, packed=True)
    for operator_id, text, lit, icon_value, props in items:
        logo_chip(line, operator_id, text, lit, icon_value, **props)
    return line
