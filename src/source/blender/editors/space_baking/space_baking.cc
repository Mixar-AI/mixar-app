/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spbaking
 *
 * Texturing Baking Space - Texture baking and processing operations.
 */

#include <cstring>

#include "CLG_log.h"

#include "MEM_guardedalloc.h"

/* Define logging module for baking operations. */
CLG_LOGREF_DECLARE_GLOBAL(LOG_BAKING, "ed.baking");

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

#include "baking_intern.hh"

static SpaceLink *baking_create(const ScrArea * /*area*/, const Scene * /*scene*/)
{
  SpaceBaking *sbaking = MEM_callocN<SpaceBaking>("initbaking");
  sbaking->spacetype = SPACE_BAKING;

  /* Header (hosts the editor-type switch dropdown) */
  ARegion *region = BKE_area_region_new();
  BLI_addtail(&sbaking->regionbase, region);
  region->regiontype = RGN_TYPE_HEADER;
  region->alignment = (U.uiflag & USER_HEADER_BOTTOM) ? RGN_ALIGN_BOTTOM : RGN_ALIGN_TOP;

  /* Main region */
  region = BKE_area_region_new();
  BLI_addtail(&sbaking->regionbase, region);
  region->regiontype = RGN_TYPE_WINDOW;

  return (SpaceLink *)sbaking;
}

static void baking_free(SpaceLink * /*sl*/) {}

static void baking_init(wmWindowManager * /*wm*/, ScrArea * /*area*/) {}

static SpaceLink *baking_duplicate(SpaceLink *sl)
{
  return (SpaceLink *)MEM_dupallocN(sl);
}

static void baking_main_region_init(wmWindowManager *wm, ARegion *region)
{
  ED_region_panels_init(wm, region);
}

static void baking_main_region_draw(const bContext *C, ARegion *region)
{
  ED_region_panels(C, region);
}

static void baking_main_region_listener(const wmRegionListenerParams *params)
{
  ARegion *region = params->region;
  const wmNotifier *wmn = params->notifier;

  switch (wmn->category) {
    case NC_MATERIAL:
    case NC_SPACE:
      ED_region_tag_redraw(region);
      break;
  }
}

/* Header region uses the standard header draw so Python `Header` classes
 * (and the editor-type switch dropdown) are rendered. */
static void baking_header_region_init(wmWindowManager * /*wm*/, ARegion *region)
{
  ED_region_header_init(region);
}

static void baking_header_region_draw(const bContext *C, ARegion *region)
{
  ED_region_header(C, region);
}

static void baking_header_region_listener(const wmRegionListenerParams *params)
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

static void baking_blend_write(BlendWriter *writer, SpaceLink *sl)
{
  BLO_write_struct(writer, SpaceBaking, sl);
}

static void baking_operatortypes()
{
  /* Pixel operations. */
  WM_operatortype_append(BAKING_OT_copy_image_pixels);
  WM_operatortype_append(BAKING_OT_copy_image_channel_pixels);
  WM_operatortype_append(BAKING_OT_set_image_pixels);

  /* Color space operations. */
  WM_operatortype_append(BAKING_OT_pixels_to_srgb);
  WM_operatortype_append(BAKING_OT_pixels_to_linear);
  WM_operatortype_append(BAKING_OT_batch_srgb_to_linear);
  WM_operatortype_append(BAKING_OT_batch_linear_to_srgb);

  /* Alpha operations. */
  WM_operatortype_append(BAKING_OT_multiply_rgb_by_alpha);
  WM_operatortype_append(BAKING_OT_divide_rgb_by_alpha);

  /* Filter operations. */
  WM_operatortype_append(BAKING_OT_gaussian_blur);
  WM_operatortype_append(BAKING_OT_box_blur);
  WM_operatortype_append(BAKING_OT_bilateral_filter);
  WM_operatortype_append(BAKING_OT_fxaa);

  /* Morphological operations. */
  WM_operatortype_append(BAKING_OT_dilate);
  WM_operatortype_append(BAKING_OT_erode);
  WM_operatortype_append(BAKING_OT_sobel_edge_detect);

  /* Statistics operations. */
  WM_operatortype_append(BAKING_OT_get_image_minmax);
  WM_operatortype_append(BAKING_OT_normalize_image);

  /* Normal map operations. */
  WM_operatortype_append(BAKING_OT_height_to_normal);
  WM_operatortype_append(BAKING_OT_blend_normal_maps);

  /* Blend operations. */
  WM_operatortype_append(BAKING_OT_blend_images);
  WM_operatortype_append(BAKING_OT_dither_image);
}

void ED_spacetype_baking()
{
  std::unique_ptr<SpaceType> st = std::make_unique<SpaceType>();

  st->spaceid = SPACE_BAKING;
  STRNCPY_UTF8(st->name, "Texturing Baking Space");
  st->iconid = ICON_RENDER_RESULT;

  st->create = baking_create;
  st->free = baking_free;
  st->init = baking_init;
  st->duplicate = baking_duplicate;
  st->operatortypes = baking_operatortypes;
  st->blend_write = baking_blend_write;

  /* Main region */
  ARegionType *art = MEM_callocN<ARegionType>("spacetype baking main");
  art->regionid = RGN_TYPE_WINDOW;
  art->keymapflag = ED_KEYMAP_UI;
  art->init = baking_main_region_init;
  art->layout = ED_region_panels_layout;
  art->draw = baking_main_region_draw;
  art->listener = baking_main_region_listener;
  BLI_addhead(&st->regiontypes, art);

  /* Header region */
  art = MEM_callocN<ARegionType>("spacetype baking header");
  art->regionid = RGN_TYPE_HEADER;
  art->prefsizey = HEADERY;
  art->keymapflag = ED_KEYMAP_UI | ED_KEYMAP_HEADER;
  art->init = baking_header_region_init;
  art->draw = baking_header_region_draw;
  art->listener = baking_header_region_listener;
  BLI_addhead(&st->regiontypes, art);

  BKE_spacetype_register(std::move(st));
}
