/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 *
 * Mixie Space - Main dispatcher and space registration.
 * Drawing and operator implementations are in separate modular files.
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

#include "GPU_framebuffer.hh"
#include "GPU_state.hh"

#include "BLO_read_write.hh"

#include "RNA_access.hh"

#include "DNA_scene_types.h"
#include "DNA_space_types.h"

#include "mixie_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

using namespace blender::ed::mixie;

/* Mixie carries richer generation controls than Blender's generic sidebar.
 * Keep this editor-specific so View3D and Image Editor defaults stay intact. */
static constexpr int MIXIE_SIDEBAR_PANEL_WIDTH = 320;

/* -------------------------------------------------------------------- */
/** \name Forward Declarations
 * \{ */

static void mixie_operatortypes_keymap(wmKeyConfig *keyconf);
static void mixie_footer_region_init(wmWindowManager *wm, ARegion *region);
static void mixie_footer_region_draw(const bContext *C, ARegion *region);
static void mixie_footer_region_listener(const wmRegionListenerParams *params);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Context Access
 * \{ */

[[maybe_unused]] static SpaceMixie *CTX_wm_space_mixie(const bContext *C)
{
  ScrArea *area = CTX_wm_area(C);
  if (area && area->spacetype == SPACE_MIXIE) {
    return static_cast<SpaceMixie *>(area->spacedata.first);
  }
  return nullptr;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Space Callbacks
 * \{ */

static SpaceLink *mixie_create(const ScrArea * /*area*/, const Scene * /*scene*/)
{
  ARegion *region;
  SpaceMixie *smixie;

  smixie = MEM_new<SpaceMixie>("initmixie");
  smixie->spacetype = SPACE_MIXIE;

  /* header */
  region = BKE_area_region_new();
  BLI_addtail(&smixie->regionbase, region);
  region->regiontype = RGN_TYPE_HEADER;
  region->alignment = (U.uiflag & USER_HEADER_BOTTOM) ? RGN_ALIGN_BOTTOM : RGN_ALIGN_TOP;

  /* footer (dock strip) */
  region = BKE_area_region_new();
  BLI_addtail(&smixie->regionbase, region);
  region->regiontype = RGN_TYPE_FOOTER;
  region->alignment = RGN_ALIGN_BOTTOM;

  /* tools region (T-panel toolbar on left side) */
  region = BKE_area_region_new();
  BLI_addtail(&smixie->regionbase, region);
  region->regiontype = RGN_TYPE_TOOLS;
  region->alignment = RGN_ALIGN_LEFT;

  /* UI region (N-panel sidebar on right side) */
  region = BKE_area_region_new();
  BLI_addtail(&smixie->regionbase, region);
  region->regiontype = RGN_TYPE_UI;
  region->alignment = RGN_ALIGN_RIGHT;

  /* main region (for image grid and moodboard canvas) */
  region = BKE_area_region_new();
  BLI_addtail(&smixie->regionbase, region);
  region->regiontype = RGN_TYPE_WINDOW;

  /* Initialize View2D for moodboard mode - centered on origin where images are placed.
   * Note: These are initial values; mixie_main_region_init will set the final values
   * but will preserve cur position on subsequent resize operations. */
  region->v2d.tot.xmin = -10000.0f;
  region->v2d.tot.ymin = -10000.0f;
  region->v2d.tot.xmax = 10000.0f;
  region->v2d.tot.ymax = 10000.0f;

  /* Start with a reasonable zoom centered on origin */
  region->v2d.cur.xmin = -500.0f;
  region->v2d.cur.ymin = -500.0f;
  region->v2d.cur.xmax = 500.0f;
  region->v2d.cur.ymax = 500.0f;

  region->v2d.min[0] = 1.0f;
  region->v2d.min[1] = 1.0f;

  region->v2d.max[0] = 32000.0f;
  region->v2d.max[1] = 32000.0f;

  region->v2d.minzoom = 0.05f;
  region->v2d.maxzoom = 21.0f;

  region->v2d.scroll = (V2D_SCROLL_RIGHT | V2D_SCROLL_BOTTOM);
  region->v2d.keepzoom = V2D_LIMITZOOM;
  region->v2d.keeptot = V2D_KEEPTOT_FREE;

  return (SpaceLink *)smixie;
}

static void mixie_free(SpaceLink * /*sl*/)
{
  mixie_moodboard_free_texture_cache();
}

static void mixie_init(wmWindowManager * /*wm*/, ScrArea * /*area*/)
{
}

static SpaceLink *mixie_duplicate(SpaceLink *sl)
{
  SpaceMixie *smixien = static_cast<SpaceMixie *>(MEM_dupalloc_void(sl));
  return (SpaceLink *)smixien;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Main Region Callbacks
 * \{ */

static void mixie_main_region_init(wmWindowManager *wm, ARegion *region)
{
  /* Check if this is the first initialization by seeing if cur has valid extent.
   * We need to preserve the current view position during resize operations. */
  const bool is_first_init = (region->v2d.cur.xmax - region->v2d.cur.xmin) < 1.0f;

  /* Store current view position before reinit (if not first init) */
  rctf saved_cur = region->v2d.cur;

  /* Initialize View2D using standard Blender pattern */
  ui::view2d_region_reinit(&region->v2d, ui::V2D_COMMONVIEW_CUSTOM, region->winx, region->winy);

  /* Custom View2D settings for moodboard infinite canvas */
  region->v2d.tot.xmin = -10000.0f;
  region->v2d.tot.ymin = -10000.0f;
  region->v2d.tot.xmax = 10000.0f;
  region->v2d.tot.ymax = 10000.0f;

  /* Only reset cur to tot on first initialization, otherwise restore saved position */
  if (is_first_init) {
    /* Center the view on origin with reasonable zoom */
    region->v2d.cur.xmin = -500.0f;
    region->v2d.cur.ymin = -500.0f;
    region->v2d.cur.xmax = 500.0f;
    region->v2d.cur.ymax = 500.0f;
  }
  else {
    /* Restore the saved view position */
    region->v2d.cur = saved_cur;
  }

  region->v2d.min[0] = 1.0f;
  region->v2d.min[1] = 1.0f;
  region->v2d.max[0] = 32000.0f;
  region->v2d.max[1] = 32000.0f;

  region->v2d.minzoom = 0.05f;
  region->v2d.maxzoom = 21.0f;

  region->v2d.scroll = (V2D_SCROLL_RIGHT | V2D_SCROLL_BOTTOM);
  region->v2d.keepzoom = V2D_LIMITZOOM;
  region->v2d.keeptot = V2D_KEEPTOT_FREE;

  /* Let uiBlocks drawn over the canvas receive pointer and keyboard events
   * before the moodboard's canvas keymaps. */
  ui::region_handlers_add(&region->runtime->handlers);

  /* Setup keymap */
  wmKeyMap *keymap = WM_keymap_ensure(
      wm->runtime->defaultconf, "Mixie", SPACE_MIXIE, RGN_TYPE_WINDOW);
  mixie_operatortypes_keymap(wm->runtime->defaultconf);
  WM_event_add_keymap_handler_v2d_mask(&region->runtime->handlers, keymap);

  /* Add drop boxes for drag-and-drop */
  ListBaseT<wmDropBox> *lb = WM_dropboxmap_find("Mixie", SPACE_MIXIE, RGN_TYPE_WINDOW);
  WM_event_add_dropbox_handler(static_cast<ListBaseT<wmEventHandler> *>(&region->runtime->handlers),
                               static_cast<ListBaseT<wmDropBox> *>(lb));
}

static void mixie_main_region_draw(const bContext *C, ARegion *region)
{
  /* Moodboard reference canvas: neutral pure black, independent of the
   * selected Blender theme. Other Mixie regions continue using TH_BACK. */
  GPU_clear_color(0.0f, 0.0f, 0.0f, 1.0f);

  /* Always draw moodboard mode - panels are controlled via scene properties */
  mixie_draw_moodboard_mode(C, region);
}

static void mixie_main_region_exit(wmWindowManager *wm, ARegion * /*region*/)
{
  mixie_moodboard_video_playback_shutdown(wm);
  /* The link-drag preview lives in a file-static. Closing the region (area
   * close, workspace switch, file load) can end a drag without the modal ever
   * seeing a release, so clear it here rather than leaving a stale curve to be
   * drawn against whatever scene next matches. */
  blender::ed::mixie::moodboard_graph_link_drag_reset();
}

static void mixie_main_region_listener(const wmRegionListenerParams *params)
{
  ARegion *region = params->region;
  const wmNotifier *wmn = params->notifier;

  switch (wmn->category) {
    case NC_SPACE:
      if (wmn->data == ND_SPACE_MIXIE) {
        ED_region_tag_redraw(region);
      }
      break;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name UI Panel Region Callbacks
 * \{ */

/** \} */

/* -------------------------------------------------------------------- */
/** \name Header Region Callbacks
 * \{ */

static void mixie_header_listener(const wmRegionListenerParams *params)
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
      if (wmn->data == ND_SPACE_MIXIE) {
        ED_region_tag_redraw(region);
      }
      break;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Operator and Keymap Registration
 * \{ */

static void mixie_operatortypes()
{
  /* General operators (from mixie_ops.cc) */
  WM_operatortype_append(MIXIE_OT_sam3d_preview_select);
  WM_operatortype_append(MIXIE_OT_sam3d_preview_delete);

  /* Moodboard operators (from mixie_moodboard_ops.cc) */
  WM_operatortype_append(MIXIE_OT_moodboard_drop_image);
  WM_operatortype_append(MIXIE_OT_moodboard_select_image);
  WM_operatortype_append(MIXIE_OT_moodboard_graph_select);
  WM_operatortype_append(MIXIE_OT_moodboard_context_menu);
  WM_operatortype_append(MIXIE_OT_moodboard_video_hover);
  WM_operatortype_append(MIXIE_OT_moodboard_zoom);
  WM_operatortype_append(MIXIE_OT_moodboard_ensure_visible);
  WM_operatortype_append(MIXIE_OT_moodboard_box_select);
  WM_operatortype_append(MIXIE_OT_moodboard_generate_box_mask);
  WM_operatortype_append(MIXIE_OT_moodboard_generate_lasso_mask);
  WM_operatortype_append(MIXIE_OT_moodboard_crop_image);
}

static void mixie_operatortypes_keymap(wmKeyConfig *keyconf)
{
  wmKeyMap *keymap = WM_keymap_ensure(keyconf, "Mixie", SPACE_MIXIE, RGN_TYPE_WINDOW);

  /* Stateless hover checks leave normal click/drag keymap dispatch untouched. */
  KeyMapItem_Params hover_params{};
  hover_params.type = MOUSEMOVE;
  hover_params.value = KM_ANY;
  hover_params.modifier = 0;
  WM_keymap_add_item(keymap, "MIXIE_OT_moodboard_video_hover", &hover_params);

  /* Entering the sidebar or header also leaves the originating video tile. */
  wmKeyMap *sidebar_keymap = WM_keymap_ensure(
      keyconf, "Mixie Sidebar", SPACE_MIXIE, RGN_TYPE_UI);
  WM_keymap_add_item(sidebar_keymap, "MIXIE_OT_moodboard_video_hover", &hover_params);
  wmKeyMap *header_keymap = WM_keymap_ensure(
      keyconf, "Mixie Header", SPACE_MIXIE, RGN_TYPE_HEADER);
  WM_keymap_add_item(header_keymap, "MIXIE_OT_moodboard_video_hover", &hover_params);

  /* Select and move images in moodboard */
  KeyMapItem_Params params{};
  params.type = LEFTMOUSE;
  params.value = KM_PRESS;
  params.modifier = 0;
  /* Graph cards get first refusal; the operator passes through on media/empty space. */
  WM_keymap_add_item(keymap, "MIXIE_OT_moodboard_graph_select", &params);
  WM_keymap_add_item(keymap, "MIXIE_OT_moodboard_select_image", &params);

  /* Double-click to edit text boxes */
  KeyMapItem_Params params_dbl{};
  params_dbl.type = LEFTMOUSE;
  params_dbl.value = KM_DBL_CLICK;
  params_dbl.modifier = 0;
  WM_keymap_add_item(keymap, "MIXIE_OT_moodboard_select_image", &params_dbl);

  /* Multi-select with Shift+LEFTMOUSE. Graph cards get first refusal (same
   * ordering as the plain click above): the graph operator toggles the card
   * under the pointer and passes through everywhere else, so media extend
   * keeps working. */
  KeyMapItem_Params params_extend{};
  params_extend.type = LEFTMOUSE;
  params_extend.value = KM_PRESS;
  params_extend.modifier = KM_SHIFT;
  wmKeyMapItem *kmi_extend_graph = WM_keymap_add_item(
      keymap, "MIXIE_OT_moodboard_graph_select", &params_extend);
  RNA_boolean_set(kmi_extend_graph->ptr, "extend", true);
  wmKeyMapItem *kmi_extend = WM_keymap_add_item(
      keymap, "MIXIE_OT_moodboard_select_image", &params_extend);
  RNA_boolean_set(kmi_extend->ptr, "extend", true);

  /* Platform-native multi-select modifier: Cmd on macOS, Ctrl on
   * Windows/Linux. We only bind one or the other per OS so we don't
   * shadow native conventions (on macOS, Ctrl+click is the
   * context-menu gesture). */
  KeyMapItem_Params params_extend_native{};
  params_extend_native.type = LEFTMOUSE;
  params_extend_native.value = KM_PRESS;
#ifdef __APPLE__
  params_extend_native.modifier = KM_OSKEY;
#else
  params_extend_native.modifier = KM_CTRL;
#endif
  wmKeyMapItem *kmi_extend_native_graph = WM_keymap_add_item(
      keymap, "MIXIE_OT_moodboard_graph_select", &params_extend_native);
  RNA_boolean_set(kmi_extend_native_graph->ptr, "extend", true);
  wmKeyMapItem *kmi_extend_native = WM_keymap_add_item(
      keymap, "MIXIE_OT_moodboard_select_image", &params_extend_native);
  RNA_boolean_set(kmi_extend_native->ptr, "extend", true);

  /* Zoom selected images - Pinch Gesture */
  KeyMapItem_Params zoom_params{};
  zoom_params.type = MOUSEZOOM;
  zoom_params.value = KM_ANY;
  zoom_params.modifier = 0;
  WM_keymap_add_item(keymap, "MIXIE_OT_moodboard_zoom", &zoom_params);

  /* Box select images in moodboard - B key */
  KeyMapItem_Params box_params{};
  box_params.type = EVT_BKEY;
  box_params.value = KM_PRESS;
  box_params.modifier = 0;
  WM_keymap_add_item(keymap, "MIXIE_OT_moodboard_box_select", &box_params);

  /* Delete selected items - X key */
  KeyMapItem_Params delete_params{};
  delete_params.type = EVT_XKEY;
  delete_params.value = KM_PRESS;
  delete_params.modifier = 0;
  WM_keymap_add_item(keymap, "mixie.moodboard_delete", &delete_params);

  delete_params.type = EVT_DELKEY;
  WM_keymap_add_item(keymap, "mixie.moodboard_delete", &delete_params);
  delete_params.type = EVT_BACKSPACEKEY;
  WM_keymap_add_item(keymap, "mixie.moodboard_delete", &delete_params);

  /* Add Text Box Interactive - Cmd+T (macOS) / Ctrl+T (Windows/Linux) */
  KeyMapItem_Params text_params_mac{};
  text_params_mac.type = EVT_TKEY;
  text_params_mac.value = KM_PRESS;
  text_params_mac.modifier = KM_OSKEY;
  WM_keymap_add_item(keymap, "mixie.moodboard_add_textbox", &text_params_mac);

  KeyMapItem_Params text_params_win{};
  text_params_win.type = EVT_TKEY;
  text_params_win.value = KM_PRESS;
  text_params_win.modifier = KM_CTRL;
  WM_keymap_add_item(keymap, "mixie.moodboard_add_textbox", &text_params_win);

  /* Add Image - Cmd+I (macOS) / Ctrl+I (Windows/Linux) */
  KeyMapItem_Params add_img_params_mac{};
  add_img_params_mac.type = EVT_IKEY;
  add_img_params_mac.value = KM_PRESS;
  add_img_params_mac.modifier = KM_OSKEY;
  WM_keymap_add_item(keymap, "mixie.moodboard_add_image", &add_img_params_mac);

  KeyMapItem_Params add_img_params_win{};
  add_img_params_win.type = EVT_IKEY;
  add_img_params_win.value = KM_PRESS;
  add_img_params_win.modifier = KM_CTRL;
  WM_keymap_add_item(keymap, "mixie.moodboard_add_image", &add_img_params_win);

  /* Image Editing Tools */
  /* Crop Tool - C key */
  KeyMapItem_Params crop_params{};
  crop_params.type = EVT_CKEY;
  crop_params.value = KM_PRESS;
  crop_params.modifier = 0;
  WM_keymap_add_item(keymap, "mixie.moodboard_crop_tool", &crop_params);

  /* Box Mask Tool - M key */
  KeyMapItem_Params mask_params{};
  mask_params.type = EVT_MKEY;
  mask_params.value = KM_PRESS;
  mask_params.modifier = 0;
  WM_keymap_add_item(keymap, "mixie.moodboard_box_mask_tool", &mask_params);

  /* Lasso Tool - L key */
  KeyMapItem_Params lasso_params{};
  lasso_params.type = EVT_LKEY;
  lasso_params.value = KM_PRESS;
  lasso_params.modifier = 0;
  WM_keymap_add_item(keymap, "mixie.moodboard_lasso_tool", &lasso_params);

  /* Cancel Tool - ESC key */
  KeyMapItem_Params cancel_params{};
  cancel_params.type = EVT_ESCKEY;
  cancel_params.value = KM_PRESS;
  cancel_params.modifier = 0;
  WM_keymap_add_item(keymap, "mixie.moodboard_cancel_tool", &cancel_params);

  /* Sam3D preview delete (must be before select to handle delete button clicks) */
  KeyMapItem_Params sam3d_delete_params{};
  sam3d_delete_params.type = LEFTMOUSE;
  sam3d_delete_params.value = KM_PRESS;
  sam3d_delete_params.modifier = 0;
  WM_keymap_add_item(keymap, "MIXIE_OT_sam3d_preview_delete", &sam3d_delete_params);

  /* Sam3D preview select */
  KeyMapItem_Params sam3d_params{};
  sam3d_params.type = LEFTMOUSE;
  sam3d_params.value = KM_PRESS;
  sam3d_params.modifier = 0;
  WM_keymap_add_item(keymap, "MIXIE_OT_sam3d_preview_select", &sam3d_params);

  /* Duplicate selected items - Shift+D */
  KeyMapItem_Params duplicate_params{};
  duplicate_params.type = EVT_DKEY;
  duplicate_params.value = KM_PRESS;
  duplicate_params.modifier = KM_SHIFT;
  WM_keymap_add_item(keymap, "mixie.moodboard_duplicate", &duplicate_params);

  /* Move/Grab selected items - G key */
  KeyMapItem_Params grab_params{};
  grab_params.type = EVT_GKEY;
  grab_params.value = KM_PRESS;
  grab_params.modifier = 0;
  WM_keymap_add_item(keymap, "mixie.moodboard_grab", &grab_params);

  /* Rotate selected items 90 degrees - R key */
  KeyMapItem_Params rotate_params{};
  rotate_params.type = EVT_RKEY;
  rotate_params.value = KM_PRESS;
  rotate_params.modifier = 0;
  WM_keymap_add_item(keymap, "mixie.rotate_images", &rotate_params);

  /* Scale selected items interactively - S key */
  KeyMapItem_Params scale_params{};
  scale_params.type = EVT_SKEY;
  scale_params.value = KM_PRESS;
  scale_params.modifier = 0;
  WM_keymap_add_item(keymap, "mixie.moodboard_scale", &scale_params);

  /* Send to Chat - Cmd+P (macOS) / Ctrl+P (Windows/Linux) */
  KeyMapItem_Params send_chat_params_mac{};
  send_chat_params_mac.type = EVT_PKEY;
  send_chat_params_mac.value = KM_PRESS;
  send_chat_params_mac.modifier = KM_OSKEY;
  WM_keymap_add_item(keymap, "mixie.moodboard_send_to_chat", &send_chat_params_mac);

  KeyMapItem_Params send_chat_params_win{};
  send_chat_params_win.type = EVT_PKEY;
  send_chat_params_win.value = KM_PRESS;
  send_chat_params_win.modifier = KM_CTRL;
  WM_keymap_add_item(keymap, "mixie.moodboard_send_to_chat", &send_chat_params_win);

  /* Create Group - Cmd+G (macOS) / Ctrl+G (Windows/Linux) */
  KeyMapItem_Params group_params_mac{};
  group_params_mac.type = EVT_GKEY;
  group_params_mac.value = KM_PRESS;
  group_params_mac.modifier = KM_OSKEY;
  WM_keymap_add_item(keymap, "mixie.create_group", &group_params_mac);

  KeyMapItem_Params group_params_win{};
  group_params_win.type = EVT_GKEY;
  group_params_win.value = KM_PRESS;
  group_params_win.modifier = KM_CTRL;
  WM_keymap_add_item(keymap, "mixie.create_group", &group_params_win);

  /* Ungroup - Alt+G (all platforms) */
  KeyMapItem_Params ungroup_params{};
  ungroup_params.type = EVT_GKEY;
  ungroup_params.value = KM_PRESS;
  ungroup_params.modifier = KM_ALT;
  WM_keymap_add_item(keymap, "mixie.ungroup", &ungroup_params);

  /* Right-click context menu */
  KeyMapItem_Params context_menu_params{};
  context_menu_params.type = RIGHTMOUSE;
  context_menu_params.value = KM_PRESS;
  context_menu_params.modifier = 0;
  WM_keymap_add_item(keymap, "MIXIE_OT_moodboard_context_menu", &context_menu_params);

  /* Toggle N-panel sidebar - N key */
  KeyMapItem_Params sidebar_params{};
  sidebar_params.type = EVT_NKEY;
  sidebar_params.value = KM_PRESS;
  sidebar_params.modifier = 0;
  wmKeyMapItem *kmi_sidebar = WM_keymap_add_item(
      keymap, "SCREEN_OT_region_toggle", &sidebar_params);
  RNA_enum_set(kmi_sidebar->ptr, "region_type", RGN_TYPE_UI);
}

static void mixie_keymap(wmKeyConfig *keyconf)
{
  /* Only declare the keymap - items are added after operators are registered */
  WM_keymap_ensure(keyconf, "Mixie", SPACE_MIXIE, RGN_TYPE_WINDOW);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Tools Region Callbacks (T-Panel)
 * \{ */

static void mixie_tools_region_init(wmWindowManager *wm, ARegion *region)
{
  wmKeyMap *keymap;

  ED_region_panels_init(wm, region);

  keymap = WM_keymap_ensure(wm->runtime->defaultconf, "Mixie", SPACE_MIXIE, RGN_TYPE_WINDOW);
  WM_event_add_keymap_handler(&region->runtime->handlers, keymap);
}

static void mixie_tools_region_draw(const bContext *C, ARegion *region)
{
  ED_region_panels(C, region);
}

static void mixie_tools_region_listener(const wmRegionListenerParams *params)
{
  ARegion *region = params->region;
  const wmNotifier *wmn = params->notifier;

  switch (wmn->category) {
    case NC_SPACE:
      if (wmn->data == ND_SPACE_MIXIE) {
        ED_region_tag_redraw(region);
      }
      break;
    case NC_SCENE:
      ED_region_tag_redraw(region);
      break;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Footer Region Callbacks (Dock Strip)
 * \{ */

static void mixie_footer_region_init(wmWindowManager *wm, ARegion *region)
{
  wmKeyMap *keymap;
  ED_region_header_init(region);

  keymap = WM_keymap_ensure(wm->runtime->defaultconf, "Mixie", SPACE_MIXIE, RGN_TYPE_WINDOW);
  WM_event_add_keymap_handler(&region->runtime->handlers, keymap);
}

static void mixie_footer_region_draw(const bContext *C, ARegion *region)
{
  ED_region_header(C, region);
}

static void mixie_footer_region_listener(const wmRegionListenerParams *params)
{
  ARegion *region = params->region;
  const wmNotifier *wmn = params->notifier;

  switch (wmn->category) {
    case NC_SPACE:
      if (wmn->data == ND_SPACE_MIXIE) {
        ED_region_tag_redraw(region);
      }
      break;
    case NC_SCENE:
      ED_region_tag_redraw(region);
      break;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name UI Region Callbacks (N-Panel Sidebar)
 * \{ */

static void mixie_ui_region_init(wmWindowManager *wm, ARegion *region)
{
  ED_region_panels_init(wm, region);
}

static void mixie_ui_region_draw(const bContext *C, ARegion *region)
{
  ED_region_panels(C, region);
}

static void mixie_ui_region_listener(const wmRegionListenerParams *params)
{
  ARegion *region = params->region;
  const wmNotifier *wmn = params->notifier;

  switch (wmn->category) {
    case NC_SPACE:
      if (wmn->data == ND_SPACE_MIXIE) {
        ED_region_tag_redraw(region);
      }
      break;
    case NC_SCENE:
      ED_region_tag_redraw(region);
      break;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Blend File I/O
 * \{ */

static void mixie_space_blend_write(BlendWriter *writer, SpaceLink *sl)
{
  writer->write_struct_cast<SpaceMixie>(sl);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Space Type Registration
 * \{ */

void ED_spacetype_mixie()
{
  std::unique_ptr<SpaceType> st = std::make_unique<SpaceType>();
  ARegionType *art;

  st->spaceid = SPACE_MIXIE;
  STRNCPY_UTF8(st->name, "Mixie");
  st->iconid = ICON_NONE;

  st->create = mixie_create;
  st->free = mixie_free;
  st->init = mixie_init;
  st->duplicate = mixie_duplicate;
  st->operatortypes = mixie_operatortypes;
  st->keymap = mixie_keymap;
  st->dropboxes = mixie_dropboxes;
  st->blend_write = mixie_space_blend_write;

  /* regions: main window */
  art = MEM_new_zeroed<ARegionType>("spacetype mixie region");
  art->regionid = RGN_TYPE_WINDOW;
  art->keymapflag = ED_KEYMAP_UI | ED_KEYMAP_GIZMO | ED_KEYMAP_TOOL | ED_KEYMAP_FRAMES |
                    ED_KEYMAP_VIEW2D;

  art->init = mixie_main_region_init;
  art->exit = mixie_main_region_exit;
  art->draw = mixie_main_region_draw;
  art->listener = mixie_main_region_listener;

  BLI_addhead(&st->regiontypes, art);

  /* regions: tools (T-panel toolbar) */
  art = MEM_new_zeroed<ARegionType>("spacetype mixie tools region");
  art->regionid = RGN_TYPE_TOOLS;
  art->prefsizex = int(UI_TOOLBAR_WIDTH);
  art->prefsizey = 50;
  art->keymapflag = ED_KEYMAP_UI | ED_KEYMAP_FRAMES;

  art->init = mixie_tools_region_init;
  art->layout = ED_region_panels_layout;
  art->draw = mixie_tools_region_draw;
  art->listener = mixie_tools_region_listener;

  BLI_addhead(&st->regiontypes, art);

  /* regions: footer (dock strip) */
  art = MEM_new_zeroed<ARegionType>("spacetype mixie footer region");
  art->regionid = RGN_TYPE_FOOTER;
  art->prefsizey = HEADERY;
  art->keymapflag = ED_KEYMAP_UI | ED_KEYMAP_VIEW2D | ED_KEYMAP_FOOTER;

  art->init = mixie_footer_region_init;
  art->draw = mixie_footer_region_draw;
  art->listener = mixie_footer_region_listener;

  BLI_addhead(&st->regiontypes, art);

  /* regions: UI sidebar (N-panel on right side) */
  art = MEM_new_zeroed<ARegionType>("spacetype mixie ui region");
  art->regionid = RGN_TYPE_UI;
  art->prefsizex = MIXIE_SIDEBAR_PANEL_WIDTH;
  art->keymapflag = ED_KEYMAP_UI | ED_KEYMAP_FRAMES;

  art->listener = mixie_ui_region_listener;
  art->init = mixie_ui_region_init;
  art->layout = ED_region_panels_layout;
  art->draw = mixie_ui_region_draw;

  BLI_addhead(&st->regiontypes, art);

  /* regions: header */
  art = MEM_new_zeroed<ARegionType>("spacetype mixie region");
  art->regionid = RGN_TYPE_HEADER;
  art->prefsizey = HEADERY;

  art->keymapflag = ED_KEYMAP_UI | ED_KEYMAP_VIEW2D | ED_KEYMAP_HEADER;
  art->listener = mixie_header_listener;
  art->init = mixie_header_region_init;
  art->draw = mixie_header_region_draw;

  BLI_addhead(&st->regiontypes, art);

  /* QA harness: export moodboard canvas nodes/media/sockets as targets. */
  void mixie_moodboard_qa_targets_register();
  mixie_moodboard_qa_targets_register();

  BKE_spacetype_register(std::move(st));
}

/** \} */
}  // namespace blender
