/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup sptexturesets
 *
 * Texture Sets Space - Main dispatcher and space registration.
 * Provides Substance Painter-style texture set management per material slot.
 */

#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_listbase.h"
#include "BLI_string_utf8.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"
#include "BKE_screen.hh"

#include "ED_screen.hh"
#include "ED_space_api.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"

#include "BLO_read_write.hh"

#include "RNA_access.hh"

#include "DNA_scene_types.h"
#include "DNA_space_types.h"

#include "texture_sets_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

using namespace blender::ed::texture_sets;

/* -------------------------------------------------------------------- */
/** \name Space Callbacks
 * \{ */

static SpaceLink *texture_sets_create(const ScrArea * /*area*/, const Scene * /*scene*/)
{
  ARegion *region;
  SpaceTextureSets *stexture_sets;

  stexture_sets = MEM_new<SpaceTextureSets>("inittexturesets");
  stexture_sets->spacetype = SPACE_TEXTURE_SETS;
  stexture_sets->active_texture_set_index = 0;

  /* header */
  region = BKE_area_region_new();
  BLI_addtail(&stexture_sets->regionbase, region);
  region->regiontype = RGN_TYPE_HEADER;
  region->alignment = (U.uiflag & USER_HEADER_BOTTOM) ? RGN_ALIGN_BOTTOM : RGN_ALIGN_TOP;

  /* main region */
  region = BKE_area_region_new();
  BLI_addtail(&stexture_sets->regionbase, region);
  region->regiontype = RGN_TYPE_WINDOW;

  return (SpaceLink *)stexture_sets;
}

static void texture_sets_free(SpaceLink * /*sl*/)
{
  /* SpaceTextureSets *stexture_sets = (SpaceTextureSets *) sl; */
  /* Nothing to free yet */
}

static void texture_sets_init(wmWindowManager * /*wm*/, ScrArea * /*area*/)
{
}

static SpaceLink *texture_sets_duplicate(SpaceLink *sl)
{
  SpaceTextureSets *stexture_setsn = static_cast<SpaceTextureSets *>(MEM_dupalloc_void(sl));
  return (SpaceLink *)stexture_setsn;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Main Region Callbacks
 * \{ */

static void texture_sets_main_region_init(wmWindowManager *wm, ARegion *region)
{
  ED_region_panels_init(wm, region);
}

static void texture_sets_main_region_draw(const bContext *C, ARegion *region)
{
  ED_region_panels(C, region);
}

static void texture_sets_main_region_listener(const wmRegionListenerParams *params)
{
  ARegion *region = params->region;
  const wmNotifier *wmn = params->notifier;

  switch (wmn->category) {
    case NC_SPACE:
      if (wmn->data == ND_SPACE_PROPERTIES) {
        ED_region_tag_redraw(region);
      }
      break;
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

/** \} */

/* -------------------------------------------------------------------- */
/** \name Header Region Callbacks
 * \{ */

static void texture_sets_header_listener(const wmRegionListenerParams *params)
{
  ARegion *region = params->region;
  const wmNotifier *wmn = params->notifier;

  switch (wmn->category) {
    case NC_SCREEN:
      if (ELEM(wmn->data, ND_LAYER)) {
        ED_region_tag_redraw(region);
      }
      break;
    case NC_SPACE:
      ED_region_tag_redraw(region);
      break;
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

/** \} */

/* -------------------------------------------------------------------- */
/** \name Operator and Keymap Registration
 * \{ */

static void texture_sets_operatortypes()
{
  /* No C++ operators yet - all operators are in Python */
}

static void texture_sets_keymap(wmKeyConfig * /*keyconf*/)
{
  /* No keymaps needed yet - all functionality is in Python UI panels */
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Blend File I/O
 * \{ */

static void texture_sets_space_blend_write(BlendWriter *writer, SpaceLink *sl)
{
  writer->write_struct_cast<SpaceTextureSets>(sl);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Space Type Registration
 * \{ */

void ED_spacetype_texture_sets()
{
  std::unique_ptr<SpaceType> st = std::make_unique<SpaceType>();
  ARegionType *art;

  st->spaceid = SPACE_TEXTURE_SETS;
  STRNCPY_UTF8(st->name, "Texture Sets");
  st->iconid = ICON_MATERIAL;

  st->create = texture_sets_create;
  st->free = texture_sets_free;
  st->init = texture_sets_init;
  st->duplicate = texture_sets_duplicate;
  st->operatortypes = texture_sets_operatortypes;
  st->keymap = texture_sets_keymap;
  st->blend_write = texture_sets_space_blend_write;

  /* regions: main window */
  art = MEM_new_zeroed<ARegionType>("spacetype texture_sets region");
  art->regionid = RGN_TYPE_WINDOW;
  art->keymapflag = ED_KEYMAP_UI | ED_KEYMAP_FRAMES;

  art->init = texture_sets_main_region_init;
  art->layout = ED_region_panels_layout;
  art->draw = texture_sets_main_region_draw;
  art->listener = texture_sets_main_region_listener;

  BLI_addhead(&st->regiontypes, art);

  /* regions: header */
  art = MEM_new_zeroed<ARegionType>("spacetype texture_sets header region");
  art->regionid = RGN_TYPE_HEADER;
  art->prefsizey = HEADERY;

  art->keymapflag = ED_KEYMAP_UI | ED_KEYMAP_HEADER;
  art->listener = texture_sets_header_listener;
  art->init = texture_sets_header_region_init;
  art->draw = texture_sets_header_region_draw;

  BLI_addhead(&st->regiontypes, art);

  BKE_spacetype_register(std::move(st));
}

/** \} */
}  // namespace blender
