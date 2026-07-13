/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 */

#include "BLI_utildefines.h"

#include "BKE_context.hh"

#include "ED_screen.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"

#include "WM_types.hh"

#include "mixie_intern.hh"

/* add handlers, stuff you only do once or on area/region changes */
void mixie_header_region_init(wmWindowManager * /*wm*/, ARegion *region)
{
  ED_region_header_init(region);
}

void mixie_header_region_draw(const bContext *C, ARegion *region)
{
  ED_region_header(C, region);
}
