/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** Scene selection uses transient ID session_uids, never mutable display names.
 * Destructive actions and text editing remain standard Python-owned operators. */
#include <algorithm>
#include <cstring>

#include "BLF_api.hh"
#include "BKE_context.hh"
#include "ED_screen.hh"
#include "RNA_access.hh"
#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_mixar_tokens.hh"
#include "WM_api.hh"
#include "WM_types.hh"
#include "view3d_scenes_drawer.hh"

namespace blender {

static void invoke_edit(bContext *C, const char *idname, const char *property,
                        const std::string &value)
{
  wmOperatorType *ot = WM_operatortype_find(idname, true);
  if (!ot) {
    return;
  }
  PointerRNA props = WM_operator_properties_create_ptr(ot);
  RNA_string_set(&props, property, value.c_str());
  WM_operator_name_call_ptr(C, ot, wm::OpCallContext::InvokeDefault, &props, nullptr);
  WM_operator_properties_free(&props);
}

static void delete_selected(bContext *C, const ScenesDrawerRuntime *runtime)
{
  if (runtime->selected_uids.empty()) {
    return;
  }
  std::string ids = "[";
  for (const ScenesDrawerCard &card : runtime->cards) {
    if (!runtime->selected_uids.contains(card.scene_uid)) {
      continue;
    }
    if (ids.size() > 1) {
      ids += ',';
    }
    /* The mirror supplies decimal ID session_uids only. */
    ids += '"' + card.scene_uid + '"';
  }
  ids += ']';
  invoke_edit(C, "MIXIE_CHAT_OT_delete_scene_tabs", "scene_uids", ids);
}

bool view3d_scenes_drawer_selection_click(bContext *C, ARegion *region,
                                         ScenesDrawerRuntime *runtime, const wmEvent *event)
{
  if (!runtime->selected_uids.empty()) {
    if (BLI_rcti_isect_pt_v(&runtime->bulk_delete_rect, event->xy)) {
      delete_selected(C, runtime);
      return true;
    }
    if (BLI_rcti_isect_pt_v(&runtime->clear_selection_rect, event->xy)) {
      runtime->selected_uids.clear();
      ED_region_tag_redraw(region);
      return true;
    }
  }
  for (int i = 0; i < int(runtime->cards.size()); i++) {
    const ScenesDrawerCard &card = runtime->cards[i];
    if (!BLI_rcti_isect_pt_v(&card.rect, event->xy) ||
        BLI_rcti_isect_pt_v(&card.close_rect, event->xy)) {
      continue;
    }
    if (event->val == KM_DBL_CLICK && event->modifier == 0) {
      invoke_edit(C, "MIXIE_CHAT_OT_rename_scene_tab", "scene_uid", card.scene_uid);
      return true;
    }
    const bool extend = event->modifier & (KM_CTRL | KM_OSKEY);
    if (event->modifier & KM_SHIFT) {
      int anchor = i;
      for (int j = 0; j < int(runtime->cards.size()); j++) {
        if (runtime->cards[j].scene_uid == runtime->selection_anchor) {
          anchor = j;
          break;
        }
        if (runtime->selection_anchor.empty() && runtime->cards[j].is_active) {
          anchor = j;
        }
      }
      if (!extend) {
        runtime->selected_uids.clear();
      }
      for (int j = std::min(anchor, i); j <= std::max(anchor, i); j++) {
        runtime->selected_uids.insert(runtime->cards[j].scene_uid);
      }
      if (runtime->selection_anchor.empty()) {
        runtime->selection_anchor = runtime->cards[anchor].scene_uid;
      }
    }
    else if (extend) {
      if (!runtime->selected_uids.erase(card.scene_uid)) {
        runtime->selected_uids.insert(card.scene_uid);
      }
      runtime->selection_anchor = card.scene_uid;
    }
    else {
      return false;
    }
    ED_region_tag_redraw(region);
    return true;
  }
  return event->val == KM_DBL_CLICK; /* A double click on blank chrome is inert. */
}

static wmOperatorStatus selection_invoke(bContext *C, wmOperator *, const wmEvent *event)
{
  ARegion *region = CTX_wm_region(C);
  auto *runtime = region ? static_cast<ScenesDrawerRuntime *>(region->regiondata) : nullptr;
  if (!runtime || runtime->amount < VIEW3D_SCENES_DRAWER_ACTIVE_AMOUNT) {
    return OPERATOR_PASS_THROUGH;
  }
  if (event->type == EVT_AKEY && (event->modifier & (KM_CTRL | KM_OSKEY))) {
    for (const ScenesDrawerCard &card : runtime->cards) {
      runtime->selected_uids.insert(card.scene_uid);
    }
  }
  else if (event->type == EVT_ESCKEY && !runtime->selected_uids.empty()) {
    runtime->selected_uids.clear();
  }
  else if (ELEM(event->type, EVT_DELKEY, EVT_BACKSPACEKEY) && !runtime->selected_uids.empty()) {
    delete_selected(C, runtime);
  }
  else {
    return OPERATOR_PASS_THROUGH;
  }
  ED_region_tag_redraw(region);
  return OPERATOR_FINISHED;
}

void VIEW3D_OT_scenes_drawer_selection(wmOperatorType *ot)
{
  ot->name = "Select Scenes";
  ot->idname = "VIEW3D_OT_scenes_drawer_selection";
  ot->description = "Select all scenes, clear the selection or delete selected scenes";
  ot->invoke = selection_invoke;
  ot->poll = view3d_scenes_drawer_op_poll;
  ot->flag = OPTYPE_INTERNAL;
}

namespace view3d_scenes_drawer {

void draw_header(ScenesDrawerRuntime *runtime, ARegion *region,
                 const float x0, const float x1, const float mid, const float scale)
{
  runtime->bulk_delete_rect = runtime->clear_selection_rect = runtime->new_rect = {};
  runtime->new_visible = runtime->selected_uids.empty();
  const auto &zen = ui::mixar_tokens::mixar_zen();
  const int font = BLF_default();
  rctf action = {x1 - 96.0f * scale, x1, mid - 12.0f * scale, mid + 12.0f * scale};
  BLF_size(font, 14.0f * scale);
  const std::string title = runtime->new_visible ? "Scenes" :
      std::to_string(runtime->selected_uids.size()) + " selected";
  draw_elided(font, title, x0, mid - 0.35f * BLF_height_max(font),
              action.xmin - x0 - 6.0f * scale, zen.strong);
  BLF_size(font, 11.0f * scale);
  const auto cache_rect = [&](const rctf &rect, rcti &target) {
    BLI_rcti_rctf_copy(&target, &rect);
    BLI_rcti_translate(&target, region->winrct.xmin, region->winrct.ymin);
  };
  if (runtime->new_visible) {
    float fill[4];
    with_alpha(zen.primary, runtime->hover_new ? 1.0f : 0.85f, fill);
    draw_pill(action, fill, 12.0f * scale);
    const char *label = "+ New scene";
    BLF_color4fv(font, zen.strong);
    BLF_position(font, (action.xmin + action.xmax - BLF_width(font, label, strlen(label))) * 0.5f,
                 mid - 0.35f * BLF_height_max(font), 0.0f);
    BLF_draw(font, label, strlen(label));
    cache_rect(action, runtime->new_rect);
    return;
  }
  /* Use the same header slot as Add; selection never changes list height/scroll. */
  rctf clear = action;
  clear.xmax = x1 - 32.0f * scale;
  draw_pill(clear, zen.canvas, 6.0f * scale);
  draw_elided(font, "Clear", clear.xmin + 12.0f * scale,
              mid - 0.35f * BLF_height_max(font), BLI_rctf_size_x(&clear), zen.strong);
  cache_rect(clear, runtime->clear_selection_rect);
  rctf remove = action;
  remove.xmin = x1 - 24.0f * scale;
  float fill[4];
  with_alpha(zen.danger, runtime->hover_delete ? 0.35f : 0.18f, fill);
  draw_pill(remove, fill, 6.0f * scale);
  rcti icon;
  BLI_rcti_rctf_copy(&icon, &remove);
  draw_trash(icon, scale, zen.strong);
  cache_rect(remove, runtime->bulk_delete_rect);
}

}  // namespace view3d_scenes_drawer
}  // namespace blender
