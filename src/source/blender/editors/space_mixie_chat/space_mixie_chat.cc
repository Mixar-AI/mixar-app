/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Mixie Chat Space - Chat interface for Mixar.
 * Simple layout with header and main content area only.
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
#include "UI_view2d.hh"

#include "BLO_read_write.hh"

#include "RNA_access.hh"

#include "DNA_scene_types.h"
#include "DNA_space_types.h"

#include "mixie_chat_intern.hh"
#include "mixie_chat_footer_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Operators
 * \{ */

static void mixie_chat_operatortypes()
{
  WM_operatortype_append(MIXIE_CHAT_OT_select_text);
  WM_operatortype_append(MIXIE_CHAT_OT_copy);
  WM_operatortype_append(MIXIE_CHAT_OT_drop_image);
  WM_operatortype_append(MIXIE_CHAT_OT_agent_bubble_show);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Keymap
 * \{ */

static void mixie_chat_keymap(wmKeyConfig *keyconf)
{
  wmKeyMap *keymap = WM_keymap_ensure(keyconf, "Mixie Chat", SPACE_MIXIE_CHAT, RGN_TYPE_WINDOW);

  /* Text selection with mouse drag */
  KeyMapItem_Params select_params{};
  select_params.type = LEFTMOUSE;
  select_params.value = KM_PRESS;
  select_params.modifier = 0;
  WM_keymap_add_item(keymap, "MIXIE_CHAT_OT_select_text", &select_params);

  /* Copy with Cmd+C (macOS) / Ctrl+C (other platforms) */
  KeyMapItem_Params copy_params{};
  copy_params.type = EVT_CKEY;
  copy_params.value = KM_PRESS;
#ifdef __APPLE__
  copy_params.modifier = KM_OSKEY;
#else
  copy_params.modifier = KM_CTRL;
#endif
  WM_keymap_add_item(keymap, "MIXIE_CHAT_OT_copy", &copy_params);

  /* Ctrl+V / Cmd+V: paste image or text into chat.
   * Added to the main "Mixie Chat" keymap (not a separate footer keymap)
   * to avoid keyconfig lookup mismatches. The footer region also registers
   * this keymap as a handler so the binding works in both regions. */
  KeyMapItem_Params paste_params{};
  paste_params.type = EVT_VKEY;
  paste_params.value = KM_PRESS;
#ifdef __APPLE__
  paste_params.modifier = KM_OSKEY;
#else
  paste_params.modifier = KM_CTRL;
#endif
  WM_keymap_add_item(keymap, "MIXIE_CHAT_OT_paste_image", &paste_params);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Space Callbacks
 * \{ */

static SpaceLink *mixie_chat_create(const ScrArea * /*area*/, const Scene * /*scene*/)
{
  ARegion *region;
  SpaceMixieChat *smixie_chat;

  smixie_chat = MEM_new<SpaceMixieChat>("initmixiechat");
  smixie_chat->spacetype = SPACE_MIXIE_CHAT;

  /* Initialize selection state */
  smixie_chat->sel_message_index = -1;
  smixie_chat->sel_start = 0;
  smixie_chat->sel_end = 0;

  /* Allocate per-instance runtime */
  smixie_chat->runtime = nullptr;  /* Lazily allocated on first use */

  /* Header region */
  region = BKE_area_region_new();
  BLI_addtail(&smixie_chat->regionbase, region);
  region->regiontype = RGN_TYPE_HEADER;
  region->alignment = (U.uiflag & USER_HEADER_BOTTOM) ? RGN_ALIGN_BOTTOM : RGN_ALIGN_TOP;

  /* Footer region (for chat input - fixed at bottom)
   * CRITICAL FIX: Use RGN_TYPE_TOOLS instead of RGN_TYPE_FOOTER!
   * Blender's layout system HARDCODES footer regions to max ~52px.
   * TOOLS regions support dynamic sizing and respect sizey requests. */
  region = BKE_area_region_new();
  BLI_addtail(&smixie_chat->regionbase, region);
  region->regiontype = RGN_TYPE_TOOLS;  /* Was RGN_TYPE_FOOTER - tools regions support dynamic size */
  region->alignment = RGN_ALIGN_BOTTOM;  /* Position at bottom like a footer */
  region->sizey = 50;  /* Compact height for input + mode buttons */
  /* DO NOT set RGN_FLAG_HIDDEN - region must be visible from creation to initialize properly */

  /* Main region (for chat content - uses panel system) */
  region = BKE_area_region_new();
  BLI_addtail(&smixie_chat->regionbase, region);
  region->regiontype = RGN_TYPE_WINDOW;

  return (SpaceLink *)smixie_chat;
}

static void mixie_chat_free(SpaceLink *sl)
{
  SpaceMixieChat *smixie_chat = (SpaceMixieChat *)sl;

  /* Free per-instance runtime data (layout cache, empty prompts, etc.) */
  mixie_chat_free_runtime(smixie_chat);

  /* Clear footer cache (declared in mixie_chat_footer_cache.cc) */
  footer_cache_clear();

  /* Clear property caches (declared in mixie_chat_props.cc) */
  mixie_chat_clear_property_caches();
}

static void mixie_chat_init(wmWindowManager * /*wm*/, ScrArea *area)
{
  /* Initialize footer (TOOLS) region size */
  if (area) {
    for (ARegion &region_iter : area->regionbase) {
      ARegion *region = &region_iter;
      if (region->regiontype == RGN_TYPE_TOOLS && region->alignment == RGN_ALIGN_BOTTOM) {
        region->sizey = 50;  /* Compact height for input + mode buttons */
        region->flag &= ~(RGN_FLAG_HIDDEN | RGN_FLAG_TOO_SMALL);  /* Ensure visible */
        break;
      }
    }
  }
}

static SpaceLink *mixie_chat_duplicate(SpaceLink *sl)
{
  SpaceMixieChat *smixie_chat_new = static_cast<SpaceMixieChat *>(MEM_dupalloc_void(sl));
  /* New instance gets its own fresh runtime — don't share with source */
  smixie_chat_new->runtime = nullptr;
  return (SpaceLink *)smixie_chat_new;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Header Region Callbacks
 * \{ */

static void mixie_chat_header_listener(const wmRegionListenerParams *params)
{
  ARegion *region = params->region;
  const wmNotifier *wmn = params->notifier;

  switch (wmn->category) {
    case NC_SCREEN:
      if (ELEM(wmn->data, ND_LAYER, ND_ANIMPLAY)) {
        ED_region_tag_redraw(region);
      }
      break;
    case NC_SPACE:
      if (wmn->data == ND_SPACE_MIXIE_CHAT) {
        ED_region_tag_redraw(region);
      }
      break;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Footer Region Callbacks
 * \{ */

static void mixie_chat_footer_region_listener(const wmRegionListenerParams *params)
{
  ARegion *region = params->region;
  const wmNotifier *wmn = params->notifier;

  /* Session state / pending-attachment changes arrive through the
   * Python message store, which tags the chat areas explicitly
   * (redraw_chat_areas), and through the NC_WINDOW fallback that RNA
   * broadcasts for ID-property writes. The previous NC_SCENE catch-all
   * and NC_WM|ND_JOB case additionally repainted the footer on every
   * scene edit and background-job tick (bakes, renders) for no visible
   * benefit. */
  switch (wmn->category) {
    case NC_SPACE:
      if (wmn->data == ND_SPACE_MIXIE_CHAT) {
        ED_region_tag_redraw(region);
      }
      break;
    case NC_WINDOW:
    case NC_SCREEN:
      /* Theme or window changes may affect footer sizing (padding, thumbnails, etc.)
       * Trigger size update to recalculate footer height based on new theme values. */
      if (wmn->action == NA_EDITED || wmn->category == NC_WINDOW) {
        /* Force footer cache invalidation on theme changes.
         * This ensures padding/margin updates from Theme Editor take effect immediately. */
        footer_cache_invalidate();

        ScrArea *area = params->area;
        if (area) {
          ED_area_tag_region_size_update(area, region);
        }
        ED_region_tag_redraw(region);
      }
      break;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Space-Level Listener
 * \{ */

static void mixie_chat_space_listener(const wmSpaceTypeListenerParams *params)
{
  ScrArea *area = params->area;
  const wmNotifier *wmn = params->notifier;

  switch (wmn->category) {
    case NC_WINDOW:
      /* Theme changes trigger NC_WINDOW notifications.
       * Tag entire area for redraw to apply new theme colors. */
      ED_area_tag_redraw(area);
      break;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Blend File I/O
 * \{ */

static void mixie_chat_space_blend_write(BlendWriter *writer, SpaceLink *sl)
{
  SpaceMixieChat *smixie = (SpaceMixieChat *)sl;
  /* Don't save runtime pointer — it's regenerated on load */
  void *runtime_backup = smixie->runtime;
  smixie->runtime = nullptr;
  writer->write_struct_cast<SpaceMixieChat>(sl);
  smixie->runtime = runtime_backup;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Space Type Registration
 * \{ */

void ED_spacetype_mixie_chat()
{
  std::unique_ptr<SpaceType> st = std::make_unique<SpaceType>();
  ARegionType *art;

  st->spaceid = SPACE_MIXIE_CHAT;
  STRNCPY_UTF8(st->name, "MixieChat");
  st->iconid = ICON_CONSOLE;

  st->create = mixie_chat_create;
  st->free = mixie_chat_free;
  st->init = mixie_chat_init;
  st->duplicate = mixie_chat_duplicate;
  st->operatortypes = mixie_chat_operatortypes;
  st->keymap = mixie_chat_keymap;
  st->dropboxes = mixie_chat_dropboxes;
  st->blend_write = mixie_chat_space_blend_write;
  st->listener = mixie_chat_space_listener;

  /* regions: main window (custom chat drawing) */
  art = MEM_new_zeroed<ARegionType>("spacetype mixie_chat region");
  art->regionid = RGN_TYPE_WINDOW;
  /* NO keymapflag here: most of the region uses custom GPU drawing. ED_KEYMAP_UI
   * would also add the broad "User Interface" keymap, which can consume LEFTMOUSE
   * before the chat handler. main_region_init installs only the ui::Block handler
   * needed by the embedded feedback text field, then adds chat-specific handlers. */
  art->keymapflag = 0;

  art->init = mixie_chat_main_region_init;
  art->layout = mixie_chat_main_region_layout;  /* Update View2D when footer resizes */
  art->draw = mixie_chat_main_region_draw;
  art->exit = mixie_chat_main_region_exit;  /* Stop the animation frame pump */
  art->listener = mixie_chat_main_region_listener;
  art->cursor = mixie_chat_main_region_cursor;  /* Hover tracking for option bubbles */
  /* Run the cursor callback on every mouse move, not just on region entry or
   * explicit refresh (region_cursor_set_ex gates on this flag). This keeps
   * history rows, option bubbles, stars, chips, and links responsive while
   * the cursor moves across them. */
  art->event_cursor = true;

  BLI_addhead(&st->regiontypes, art);

  /* regions: header */
  art = MEM_new_zeroed<ARegionType>("spacetype mixie_chat header region");
  art->regionid = RGN_TYPE_HEADER;
  art->prefsizey = HEADERY;

  art->keymapflag = ED_KEYMAP_UI | ED_KEYMAP_HEADER;
  art->listener = mixie_chat_header_listener;
  art->init = mixie_chat_header_region_init;
  art->draw = mixie_chat_header_region_draw;

  BLI_addhead(&st->regiontypes, art);

  /* regions: footer (implemented as TOOLS region for dynamic sizing) */
  art = MEM_new_zeroed<ARegionType>("spacetype mixie_chat footer region");
  art->regionid = RGN_TYPE_TOOLS;  /* CRITICAL: Use TOOLS not FOOTER for dynamic sizing */
  /* Footer uses ultra-compact sizing:
   * - Input row (~20px)
   * - Mode buttons row (~20px)
   * - Padding (~12px total)
   * Minimum: ~50px, with attachments: ~100px
   * TOOLS regions respect prefsizey, unlike FOOTER which is capped at ~52px */
  art->prefsizey = 50;

  /* FIX: Remove View2D to allow footer button interactions */
  art->keymapflag = ED_KEYMAP_UI | ED_KEYMAP_FOOTER;
  art->listener = mixie_chat_footer_region_listener;
  art->init = mixie_chat_footer_region_init;
  art->layout = mixie_chat_footer_region_layout;  /* Dynamic sizing for pending attachments */
  art->draw = mixie_chat_footer_region_draw;

  BLI_addhead(&st->regiontypes, art);

  /* QA harness: export chat action/gate buttons + feedback stars as targets. */
  void mixie_chat_qa_targets_register();
  mixie_chat_qa_targets_register();

  BKE_spacetype_register(std::move(st));
}

/** \} */
}  // namespace blender
