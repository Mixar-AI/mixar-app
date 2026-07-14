/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixarlayers
 *
 * Mixar Layers Space - Texture layer stack management.
 */

#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_listbase.h"
#include "BLI_string_utf8.h"

#include "BKE_context.hh"
#include "BKE_screen.hh"

#include "ED_screen.hh"
#include "ED_space_api.hh"

#include "WM_api.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"

#include "BLO_read_write.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_userdef_types.h"

static SpaceLink *mixar_layers_create(const ScrArea * /*area*/, const Scene * /*scene*/)
{
  SpaceMixarLayers *slayers = MEM_callocN<SpaceMixarLayers>("initmixarlayers");
  slayers->spacetype = SPACE_MIXAR_LAYERS;

  /* Top bar region (using RGN_TYPE_TOOL_PROPS for custom height) */
  ARegion *region = BKE_area_region_new();
  BLI_addtail(&slayers->regionbase, region);
  region->regiontype = RGN_TYPE_TOOL_PROPS;
  region->alignment = RGN_ALIGN_TOP;
  region->flag |= RGN_FLAG_NO_USER_RESIZE;

  /* Bottom bar region (using RGN_TYPE_EXECUTE for custom height) */
  region = BKE_area_region_new();
  BLI_addtail(&slayers->regionbase, region);
  region->regiontype = RGN_TYPE_EXECUTE;
  region->alignment = RGN_ALIGN_BOTTOM;
  region->flag |= RGN_FLAG_NO_USER_RESIZE;

  /* Main region */
  region = BKE_area_region_new();
  BLI_addtail(&slayers->regionbase, region);
  region->regiontype = RGN_TYPE_WINDOW;

  return (SpaceLink *)slayers;
}

static void mixar_layers_free(SpaceLink * /*sl*/) {}

static void mixar_layers_init(wmWindowManager * /*wm*/, ScrArea * /*area*/) {}

static SpaceLink *mixar_layers_duplicate(SpaceLink *sl)
{
  return (SpaceLink *)MEM_dupallocN(sl);
}

static void mixar_layers_main_region_init(wmWindowManager *wm, ARegion *region)
{
  ED_region_panels_init(wm, region);
}

static void mixar_layers_main_region_draw(const bContext *C, ARegion *region)
{
  ED_region_panels(C, region);
}

static void mixar_layers_main_region_listener(const wmRegionListenerParams *params)
{
  ARegion *region = params->region;
  const wmNotifier *wmn = params->notifier;

  switch (wmn->category) {
    case NC_MATERIAL:
    case NC_OBJECT:
    case NC_SPACE:
      ED_region_tag_redraw(region);
      break;
  }
}

/* ************************ top bar region ************************ */

static void mixar_layers_topbar_region_init(wmWindowManager * /*wm*/, ARegion *region)
{
  /* Use header init - no scrolling */
  ED_region_header_init(region);
}

static void mixar_layers_topbar_region_draw(const bContext *C, ARegion *region)
{
  /* Draw as header - no scrolling */
  ED_region_header(C, region);
}

static void mixar_layers_topbar_region_listener(const wmRegionListenerParams *params)
{
  ARegion *region = params->region;
  const wmNotifier *wmn = params->notifier;

  switch (wmn->category) {
    case NC_SCREEN:
    case NC_SPACE:
    case NC_MATERIAL:
      ED_region_tag_redraw(region);
      break;
    case NC_OBJECT:
      if (wmn->data == ND_OB_ACTIVE) {
        ED_region_tag_redraw(region);
      }
      break;
  }
}

/* ************************ bottom bar region ************************ */

static void mixar_layers_bottombar_region_init(wmWindowManager * /*wm*/, ARegion *region)
{
  /* Use header init - no scrolling */
  ED_region_header_init(region);
}

static void mixar_layers_bottombar_region_draw(const bContext *C, ARegion *region)
{
  /* Draw as header - no scrolling */
  ED_region_header(C, region);
}

static void mixar_layers_bottombar_region_listener(const wmRegionListenerParams *params)
{
  ARegion *region = params->region;
  const wmNotifier *wmn = params->notifier;

  switch (wmn->category) {
    case NC_SCREEN:
    case NC_SPACE:
    case NC_MATERIAL:
      ED_region_tag_redraw(region);
      break;
    case NC_OBJECT:
      if (wmn->data == ND_OB_ACTIVE) {
        ED_region_tag_redraw(region);
      }
      break;
  }
}

static void mixar_layers_blend_write(BlendWriter *writer, SpaceLink *sl)
{
  BLO_write_struct(writer, SpaceMixarLayers, sl);
}

void ED_spacetype_mixar_layers()
{
  std::unique_ptr<SpaceType> st = std::make_unique<SpaceType>();
  ARegionType *art;

  st->spaceid = SPACE_MIXAR_LAYERS;
  STRNCPY_UTF8(st->name, "Texturing Layers");
  st->iconid = ICON_RENDERLAYERS;

  st->create = mixar_layers_create;
  st->free = mixar_layers_free;
  st->init = mixar_layers_init;
  st->duplicate = mixar_layers_duplicate;
  st->blend_write = mixar_layers_blend_write;

  /* Main region */
  art = MEM_callocN<ARegionType>("spacetype mixar_layers main");
  art->regionid = RGN_TYPE_WINDOW;
  art->keymapflag = ED_KEYMAP_UI;
  art->init = mixar_layers_main_region_init;
  art->layout = ED_region_panels_layout;
  art->draw = mixar_layers_main_region_draw;
  art->listener = mixar_layers_main_region_listener;
  BLI_addhead(&st->regiontypes, art);

  /* Top bar region - custom height, non-scrollable */
  art = MEM_callocN<ARegionType>("spacetype mixar_layers topbar");
  art->regionid = RGN_TYPE_TOOL_PROPS;
  art->prefsizey = 40;  /* Custom height in pixels - adjustable */
  art->keymapflag = ED_KEYMAP_UI;
  art->listener = mixar_layers_topbar_region_listener;
  art->init = mixar_layers_topbar_region_init;
  art->draw = mixar_layers_topbar_region_draw;
  BLI_addhead(&st->regiontypes, art);

  /* Bottom bar region - custom height, non-scrollable */
  art = MEM_callocN<ARegionType>("spacetype mixar_layers bottombar");
  art->regionid = RGN_TYPE_EXECUTE;
  art->prefsizey = 30;  /* Custom height in pixels - adjustable */
  art->keymapflag = ED_KEYMAP_UI;
  art->listener = mixar_layers_bottombar_region_listener;
  art->init = mixar_layers_bottombar_region_init;
  art->draw = mixar_layers_bottombar_region_draw;
  BLI_addhead(&st->regiontypes, art);

  BKE_spacetype_register(std::move(st));
}
