# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Only the published card column may claim events, on BOTH axes.

Stock `ED_region_contains_xy` clips a TOP/BOTTOM-aligned overlap region on X
alone. The Parallel Agents panel is BOTTOM-aligned and taller than its cards,
and the notification lane stacks directly above them, so every press on a toast
over a short stack routed to the panel's region, missed every card and was
lost: "View Queue" and the toast's close did nothing, and the viewport could
not be orbited from that band either.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEADER = ROOT / "src/source/blender/editors/space_view3d/view3d_agent_panel.hh"
AREA_QUERY = ROOT / "src/source/blender/editors/screen/area_query.cc"
TOASTS = ROOT / "src/scripts/mixar/modules/common/notifications/constants.py"


def _defines(text):
    return {
        m.group(1): int(m.group(2))
        for m in re.finditer(r"^#define\s+(AGENT_PANEL_\w+)\s+(\d+)", text, re.M)
    }


def _contains_xy_body():
    text = AREA_QUERY.read_text()
    start = text.index("bool ED_region_contains_xy(")
    return text[start : text.index("\nARegion *ED_area_find_region_xy_visual(", start)]


def test_a_short_stack_puts_toast_actions_inside_the_panel_band():
    """Why the clip is needed: with one card the whole lowest action button sits
    inside the region's rectangle. Toast constants use the 2x authored
    baseline; the panel's are UI units."""
    panel = _defines(HEADER.read_text())
    toast = dict(re.findall(r"^(TOAST_\w+|BUTTON_HEIGHT) = (\d+)", TOASTS.read_text(), re.M))
    stack_top = panel["AGENT_PANEL_MARGIN_BOTTOM"] + panel["AGENT_PANEL_CARD_HEIGHT"]
    button_top = stack_top + (
        int(toast["TOAST_MARGIN"]) + int(toast["TOAST_PADDING_Y"]) + int(toast["BUTTON_HEIGHT"])
    ) / 2
    assert button_top < panel["AGENT_PANEL_PREFSIZEY"]


def test_the_panel_region_is_clipped_on_both_axes():
    body = _contains_xy_body()
    branch = body.index("region->regiontype == RGN_TYPE_EXECUTE")
    clip = body.index("return ED_region_overlap_isect_xy(region, event_xy);", branch)
    stock = body.index("ELEM(alignment, RGN_ALIGN_TOP, RGN_ALIGN_BOTTOM)")
    assert branch < clip < stock, (
        "the panel must be clipped before the stock X-only bottom-dock rule"
    )
    assert body.index("if (region->overlap)") < branch, (
        "EXECUTE overlaps only in View3D; outside overlap it is a plain bar"
    )
