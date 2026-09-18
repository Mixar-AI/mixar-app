/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 */

#include "BKE_screen.hh"

#include "ED_screen.hh"

#include "WM_api.hh"

#include "mixie_chat_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

void mixie_chat_header_region_init(wmWindowManager * /*wm*/, ARegion *region)
{
  ED_region_header_init(region);
}

void mixie_chat_header_region_draw(const bContext *C, ARegion *region)
{
  ED_region_header(C, region);
}
}  // namespace blender
