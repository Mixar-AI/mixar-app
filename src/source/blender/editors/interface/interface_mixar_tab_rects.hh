/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Mixar: the draw-derived hit-rects of the Mixar category tab strip.
 *
 * Blender 5.2 removed `PanelCategoryDyn::rect` (upstream tabs became real
 * buttons), so the rects of the Mixar-drawn strip are recorded here at draw
 * time and hit-tested by the MIXAR hook in interface_panel.cc.
 *
 * The readers -- #UI_mixar_panel_category_find_at and
 * #UI_mixar_panel_category_tab_rect_get -- are declared in
 * interface_mixar_section.hh, next to the rest of the public section API. This
 * header is the internal half: the record type and the writer the strip's draw
 * calls once it has laid the tabs out.
 */

#pragma once

#include "BLI_vector.hh"

#include "DNA_screen_types.h"

/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui {

struct MixarCategoryTabRect {
  char idname[64];
  rcti rect;
};

/**
 * Record `tabs` as the strip's hit-rects for `region`, replacing whatever the
 * previous draw of that region left.
 *
 * This is a DRAW-DERIVED cache: every entry is rewritten by the next draw of
 * its region, so dropping entries is always safe -- the worst case is a click
 * landing before the first repopulating draw, which finds nothing and falls
 * through, exactly as it does for a region that has never drawn. The map is
 * bounded, and the region's `winrct` is recorded alongside so a recycled
 * ARegion pointer cannot serve a dead region's tab idnames.
 */
void mixar_category_tabs_store(const ARegion *region, Vector<MixarCategoryTabRect> &&tabs);

}  // namespace blender::ui
