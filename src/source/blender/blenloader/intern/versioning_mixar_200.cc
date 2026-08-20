/* SPDX-FileCopyrightText: 2024 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup blenloader
 *
 * Mixar-specific versioning code for handling space and region updates.
 */

#include "BLI_listbase.h"
#include "BLI_utildefines.h"

#include "BKE_blender_version.h"
#include "BKE_main.hh"
#include "BKE_screen.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_userdef_types.h"

#include "versioning_common.hh"
#include "versioning_mixar_200.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

void blo_do_versions_mixar(Main *bmain)
{
  /* Pre-versioning files have mixar_versionfile == 0.
   * All existing migrations must run on those files. */
  if (!MAIN_MIXAR_VERSION_FILE_ATLEAST(bmain, 100, 1)) {
    for (bScreen &screen_iter : bmain->screens) {
      bScreen *screen = &screen_iter;
      for (ScrArea &area_iter : screen->areabase) {
        ScrArea *area = &area_iter;
        for (SpaceLink &sl_iter : area->spacedata) {
          SpaceLink *sl = &sl_iter;

          /* Remap old Mixar space type values (24-31) to new range (100-107).
           * The enum values were moved to avoid collisions with upstream Blender. */
          switch (sl->spacetype) {
            case 24: sl->spacetype = SPACE_MIXIE; break;
            case 25: sl->spacetype = SPACE_MIXAR_LAYERS; break;
            case 26: sl->spacetype = SPACE_MIXAR_PROPERTIES; break;
            case 27: sl->spacetype = SPACE_MIXAR_ASSETS; break;
            case 28: sl->spacetype = SPACE_EMPTY; break;  /* Was SPACE_MIXAR_UV_PROPERTIES */
            case 29: sl->spacetype = SPACE_BAKING; break;
            case 30: sl->spacetype = SPACE_TEXTURE_SETS; break;
            case 31: sl->spacetype = SPACE_MIXIE_CHAT; break;
            default: break;
          }

          /* Add TOOLS region to MIXIE spaces (ensures toolbar region exists). */
          if (sl->spacetype == SPACE_MIXIE) {
            ListBase *regionbase = (sl == area->spacedata.first) ? &area->regionbase :
                                                                   &sl->regionbase;
            if (ARegion *new_tools = do_versions_add_region_if_not_found(
                    regionbase, RGN_TYPE_TOOLS, "tools region", RGN_TYPE_UI))
            {
              new_tools->alignment = RGN_ALIGN_LEFT;
            }
          }
        }
      }
    }
  }

  /* Add a header region (which hosts the editor-type switch dropdown) to the
   * texturing spaces that originally shipped without one. Without this, areas
   * stored in the bundled startup file keep their saved (header-less) regions
   * and the space switcher dropdown stays hidden. */
  if (!MAIN_MIXAR_VERSION_FILE_ATLEAST(bmain, 100, 2)) {
    for (bScreen &screen_iter : bmain->screens) {
      bScreen *screen = &screen_iter;
      for (ScrArea &area_iter : screen->areabase) {
        ScrArea *area = &area_iter;
        for (SpaceLink &sl_iter : area->spacedata) {
          SpaceLink *sl = &sl_iter;
          if (!ELEM(sl->spacetype,
                    SPACE_MIXAR_PROPERTIES,
                    SPACE_MIXAR_ASSETS,
                    SPACE_BAKING))
          {
            continue;
          }

          ListBase *regionbase = (sl == area->spacedata.first) ? &area->regionbase :
                                                                 &sl->regionbase;
          ARegion *new_header = do_versions_add_region_if_not_found(
              regionbase, RGN_TYPE_HEADER, "header for texturing space", RGN_TYPE_WINDOW);
          if (new_header == nullptr) {
            continue;
          }

          new_header->alignment = (U.uiflag & USER_HEADER_BOTTOM) ? RGN_ALIGN_BOTTOM :
                                                                    RGN_ALIGN_TOP;
          /* Header must precede the main window region in the list. */
          BLI_remlink(regionbase, new_header);
          BLI_addhead(regionbase, new_header);
        }
      }
    }
  }

  /* Add the Agent Scene Strip region (bottom-docked live tiles of scenes
   * with active agents) to View3D spaces saved before it existed. The
   * removed Scene Grid space (spacetype 109) needs no remap here: its type
   * is no longer registered, so `direct_link_area()` already falls those
   * areas back to SPACE_EMPTY on read. */
  if (!MAIN_MIXAR_VERSION_FILE_ATLEAST(bmain, 100, 3)) {
    for (bScreen &screen_iter : bmain->screens) {
      bScreen *screen = &screen_iter;
      for (ScrArea &area_iter : screen->areabase) {
        ScrArea *area = &area_iter;
        for (SpaceLink &sl_iter : area->spacedata) {
          SpaceLink *sl = &sl_iter;
          if (sl->spacetype != SPACE_VIEW3D) {
            continue;
          }
          ListBase *regionbase = (sl == area->spacedata.first) ? &area->regionbase :
                                                                 &sl->regionbase;
          if (ARegion *strip = do_versions_add_region_if_not_found(
                  regionbase, RGN_TYPE_EXECUTE, "agent scene strip region",
                  RGN_TYPE_ASSET_SHELF_HEADER))
          {
            strip->alignment = RGN_ALIGN_BOTTOM;
            strip->flag |= RGN_FLAG_TEMP_REGIONDATA;
          }
        }
      }
    }
  }

  /* Future versioning blocks go here, guarded by MAIN_MIXAR_VERSION_FILE_ATLEAST. */
}
}  // namespace blender
