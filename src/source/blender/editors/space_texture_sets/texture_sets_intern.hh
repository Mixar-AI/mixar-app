/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup sptexturesets
 */

#pragma once

#include "RNA_types.hh"

struct ARegion;
struct bContext;
struct SpaceTextureSets;
struct wmOperatorType;
struct wmWindowManager;

namespace blender::ed::texture_sets {

/* -------------------------------------------------------------------- */
/** \name Drawing Functions
 * \{ */

/** Draw main region placeholder content */
void texture_sets_draw_main_region(const bContext *C, ARegion *region);

/** \} */

}  // namespace blender::ed::texture_sets

/* -------------------------------------------------------------------- */
/** \name Region Callbacks (C linkage)
 * \{ */

/* texture_sets_header.cc */
void texture_sets_header_region_init(wmWindowManager *wm, ARegion *region);
void texture_sets_header_region_draw(const bContext *C, ARegion *region);

/** \} */
