/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** Scene selection uses transient ID session_uids, never mutable display names.
 * Destructive actions and text editing remain standard Python-owned operators. */
#include <algorithm>
#include <cmath>
#include <cstring>

#include "BLF_api.hh"
#include "BKE_context.hh"
#include "BLI_string.h"
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
      runtime->rename_uid = card.scene_uid;
      STRNCPY(runtime->rename_buffer, card.scene_name.c_str());
      ED_region_tag_redraw(region);
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

void view3d_scenes_drawer_delete_card(bContext *C, const std::string &uid)
{
  invoke_edit(C, "MIXIE_CHAT_OT_delete_scene_tabs", "scene_uids", "[\"" + uid + "\"]");
}

namespace view3d_scenes_drawer {

void draw_inline_name(const bContext *C, ARegion *region, ScenesDrawerRuntime *runtime,
                      const ScenesDrawerCard &card, const rctf &rect)
{
  ui::Block *block = ui::block_begin(C, region, "scene_card_rename", ui::EmbossType::Emboss);
  ui::Button *but = ui::uiDefBut(block, ui::ButtonType::Text, "",
      int(rect.xmin), int(rect.ymin), short(BLI_rctf_size_x(&rect)),
      short(BLI_rctf_size_y(&rect)), runtime->rename_buffer, 0.0f,
      sizeof(runtime->rename_buffer), "Scene name");
  ui::button_flag_disable(but, ui::BUT_UNDO);
  ui::button_func_set(but, [runtime, uid = card.scene_uid, current = card.scene_name](
                               bContext &context) {
    const std::string name = runtime->rename_buffer;
    runtime->rename_uid.clear();
    if (name == current) {
      /* Native text editing applies on Enter AND on any click-away, so an
       * accidental double-click must not commit: an unchanged name would
       * still pin the scene as manually named and stop automatic naming. */
      return;
    }
    wmOperatorType *ot = WM_operatortype_find("MIXIE_CHAT_OT_rename_scene_tab", true);
    if (ot) {
      PointerRNA props = WM_operator_properties_create_ptr(ot);
      RNA_string_set(&props, "scene_uid", uid.c_str());
      RNA_string_set(&props, "new_name", name.c_str());
      WM_operator_name_call_ptr(&context, ot, wm::OpCallContext::ExecDefault, &props, nullptr);
      WM_operator_properties_free(&props);
    }
  });
  /* Same lifecycle as the Outliner: native editing supplies selection, UTF-8,
   * clipboard, Enter and Escape; the draft never writes directly to an ID. */
  if (!ui::button_active_only(C, region, block, but)) {
    runtime->rename_uid.clear();
  }
  ui::block_end(C, block);
  ui::block_draw(C, block);
}

/* Baseline that centers `text`'s ink (not the font's line box) on `mid`. */
static float ink_baseline(const int font, const char *text, const float mid)
{
  rcti ink;
  BLF_boundbox(font, text, strlen(text), &ink);
  return std::round(mid - 0.5f * float(ink.ymin + ink.ymax));
}

/* Center the label's ink in `rect`: the advance width and the font's line box
 * leave the leading "+" and the cap-height glyphs visibly off-center. */
static void draw_centered_label(const int font, const char *label, const rctf &rect,
                                const float color[4])
{
  const size_t len = strlen(label);
  rcti ink;
  BLF_boundbox(font, label, len, &ink);
  BLF_color4fv(font, color);
  BLF_position(font, std::round(BLI_rctf_cent_x(&rect) - 0.5f * float(ink.xmin + ink.xmax)),
               ink_baseline(font, label, BLI_rctf_cent_y(&rect)), 0.0f);
  BLF_draw(font, label, len);
}

void draw_header(ScenesDrawerRuntime *runtime, ARegion *region,
                 const float x0, const float x1, const float mid, const float scale)
{
  /* Pill label padding and the selection actions' fixed slot, unscaled. */
  constexpr float ADD_PAD_X = 14.0f;
  constexpr float SELECTION_SLOT_W = 96.0f;
  constexpr float ACTION_GAP = 8.0f;
  constexpr float DELETE_W = 24.0f;

  runtime->bulk_delete_rect = runtime->clear_selection_rect = runtime->new_rect = {};
  runtime->new_visible = runtime->selected_uids.empty();
  const auto &zen = ui::mixar_tokens::mixar_zen();
  const int font = BLF_default();
  const float half_h = 0.5f * HEADER_ACTION_H * scale;
  const char *add_label = "+ New scene";
  BLF_size(font, 11.0f * scale);
  /* Add hugs its label with even padding; the selection actions keep a fixed
   * slot. Both are right-aligned to the cards and share one vertical band. */
  const float add_w = std::round(BLF_width(font, add_label, strlen(add_label)) +
                                 2.0f * ADD_PAD_X * scale);
  const float action_w = runtime->new_visible ? add_w : SELECTION_SLOT_W * scale;
  rctf action = {x1 - action_w, x1, mid - half_h, mid + half_h};
  BLF_size(font, 14.0f * scale);
  const std::string title = runtime->new_visible ? "Scenes" :
      std::to_string(runtime->selected_uids.size()) + " selected";
  draw_elided(font, title, x0, ink_baseline(font, title.c_str(), mid),
              action.xmin - x0 - ACTION_GAP * scale, zen.strong);
  BLF_size(font, 11.0f * scale);
  const auto cache_rect = [&](const rctf &rect, rcti &target) {
    BLI_rcti_rctf_copy(&target, &rect);
    BLI_rcti_translate(&target, region->winrct.xmin, region->winrct.ymin);
  };
  if (runtime->new_visible) {
    float fill[4];
    with_alpha(zen.primary, runtime->hover_new ? 1.0f : 0.85f, fill);
    draw_pill(action, fill, half_h);
    draw_centered_label(font, add_label, action, zen.strong);
    cache_rect(action, runtime->new_rect);
    return;
  }
  /* Use the same header band as Add; selection never changes list height/scroll. */
  rctf clear = action;
  clear.xmax = x1 - (DELETE_W + ACTION_GAP) * scale;
  draw_pill(clear, zen.canvas, 6.0f * scale);
  draw_centered_label(font, "Clear", clear, zen.strong);
  cache_rect(clear, runtime->clear_selection_rect);
  rctf remove = action;
  remove.xmin = x1 - DELETE_W * scale;
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
