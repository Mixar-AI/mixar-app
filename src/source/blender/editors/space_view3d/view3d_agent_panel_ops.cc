/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Parallel Agents panel operators: wheel/trackpad scrolling of the card
 * column, and dismissing the panel.
 *
 * Scrolling writes `runtime->scroll` only; the layout pass re-clamps it
 * against the live `scroll_max` and every reader (draw, hit test, QA targets)
 * picks the new position up from the rects it writes.
 */

#include <algorithm>
#include <cmath>

#include "BKE_context.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "ED_screen.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "UI_interface.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "view3d_agent_panel.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Shared Helpers
 * \{ */

static bool agent_panel_region_active(bContext *C)
{
  ScrArea *area = CTX_wm_area(C);
  ARegion *region = CTX_wm_region(C);
  return area && area->spacetype == SPACE_VIEW3D && region &&
         region->regiontype == RGN_TYPE_EXECUTE;
}

static AgentPanelRuntime *agent_panel_runtime_from_context(bContext *C)
{
  if (!agent_panel_region_active(C)) {
    return nullptr;
  }
  /* Never `runtime_ensure` from an operator: an operator must not allocate
   * region data on a panel that has not drawn yet. */
  return static_cast<AgentPanelRuntime *>(CTX_wm_region(C)->regiondata);
}

static bool agent_panel_op_poll(bContext *C)
{
  return agent_panel_region_active(C);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Scroll
 * \{ */

static wmOperatorStatus agent_panel_scroll_exec(bContext *C, wmOperator *op)
{
  AgentPanelRuntime *runtime = agent_panel_runtime_from_context(C);
  if (runtime == nullptr) {
    return OPERATOR_CANCELLED;
  }
  if (runtime->scroll_max <= 0.0f) {
    /* Nothing to scroll: pass the event on rather than swallowing it, so a
     * wheel over a short panel still reaches the viewport behind it. */
    return OPERATOR_PASS_THROUGH;
  }

  const int delta = RNA_int_get(op->ptr, "delta");
  const float step = float(delta) * AGENT_PANEL_SCROLL_STEP * UI_SCALE_FAC;
  runtime->scroll = std::clamp(runtime->scroll + step, 0.0f, runtime->scroll_max);

  ED_region_tag_redraw(CTX_wm_region(C));
  return OPERATOR_FINISHED;
}

/** Trackpad scrolling.
 *
 * A wheel binding alone leaves the panel unscrollable on a laptop: a trackpad
 * two-finger scroll arrives as `MOUSEPAN`, not `WHEELUP/DOWNMOUSE`, so the
 * keymap simply never matched and the gesture fell through to the viewport.
 * `WM_event_absolute_delta_y` already accounts for the "natural scrolling"
 * preference, so the sign is taken from it directly and never re-inverted
 * here — a second inversion is exactly how this came out backwards the first
 * time. A positive delta walks the column FORWARD, towards the later agents,
 * which is the direction the chevron below the stack also moves it.
 */
static wmOperatorStatus agent_panel_scroll_invoke(bContext *C,
                                                  wmOperator *op,
                                                  const wmEvent *event)
{
  if (event->type != MOUSEPAN) {
    return agent_panel_scroll_exec(C, op);
  }

  AgentPanelRuntime *runtime = agent_panel_runtime_from_context(C);
  if (runtime == nullptr) {
    return OPERATOR_CANCELLED;
  }
  if (runtime->scroll_max <= 0.0f) {
    /* Nothing to scroll: let the gesture reach the viewport behind us. */
    return OPERATOR_PASS_THROUGH;
  }

  /* Pixel-for-pixel with the gesture, which is what a trackpad user expects
   * (the wheel path moves in notches instead). */
  runtime->scroll = std::clamp(
      runtime->scroll + float(WM_event_absolute_delta_y(event)), 0.0f, runtime->scroll_max);

  ED_region_tag_redraw(CTX_wm_region(C));
  return OPERATOR_FINISHED;
}

static void VIEW3D_OT_agent_panel_scroll(wmOperatorType *ot)
{
  ot->name = "Scroll Agent Panel";
  ot->idname = "VIEW3D_OT_agent_panel_scroll";
  ot->description = "Scroll the parallel agent cards";

  ot->invoke = agent_panel_scroll_invoke;
  ot->exec = agent_panel_scroll_exec;
  ot->poll = agent_panel_op_poll;

  ot->flag = 0;

  RNA_def_int(ot->srna,
              "delta",
              1,
              -100,
              100,
              "Delta",
              "Scroll steps; positive scrolls towards later agents",
              -100,
              100);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Dismiss
 * \{ */

static wmOperatorStatus agent_panel_dismiss_exec(bContext *C, wmOperator * /*op*/)
{
  /* The cards live on the WindowManager mirror Python owns, so dismissing is
   * a write to that mirror — the region poll closes the panel on the next
   * cycle by itself. */
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return OPERATOR_CANCELLED;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *cards_prop = RNA_struct_find_property(&wm_ptr, "mixar_agent_cards");
  PropertyRNA *count_prop = RNA_struct_find_property(&wm_ptr, "mixar_agent_cards_active");
  if (cards_prop == nullptr || count_prop == nullptr) {
    return OPERATOR_CANCELLED;
  }
  RNA_property_collection_clear(&wm_ptr, cards_prop);
  RNA_property_int_set(&wm_ptr, count_prop, 0);

  WM_event_add_notifier(C, NC_WINDOW, nullptr);
  return OPERATOR_FINISHED;
}

static void VIEW3D_OT_agent_panel_dismiss(wmOperatorType *ot)
{
  ot->name = "Dismiss Agent Panel";
  ot->idname = "VIEW3D_OT_agent_panel_dismiss";
  ot->description = "Close the parallel agents panel and clear its cards";

  ot->exec = agent_panel_dismiss_exec;

  ot->flag = 0;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Click
 * \{ */

static wmOperatorStatus agent_panel_click_invoke(bContext *C,
                                                 wmOperator * /*op*/,
                                                 const wmEvent *event)
{
  ARegion *region = CTX_wm_region(C);
  AgentPanelRuntime *runtime = agent_panel_runtime_from_context(C);
  if (runtime == nullptr) {
    return OPERATOR_PASS_THROUGH;
  }

  int card_index = -1;
  const AgentPanelHit hit = view3d_agent_panel_hit_test(runtime, event->mval, &card_index);

  switch (hit) {
    case AgentPanelHit::None:
      /* Nothing of ours under the cursor: the viewport behind the panel keeps
       * the click, so an orbit drag started below the last card still works. */
      return OPERATOR_PASS_THROUGH;

    case AgentPanelHit::Chevron:
      runtime->scroll = std::clamp(runtime->scroll +
                                       AGENT_PANEL_VISIBLE_CARDS *
                                           (AGENT_PANEL_CARD_HEIGHT + AGENT_PANEL_CARD_GAP) *
                                           UI_SCALE_FAC,
                                   0.0f,
                                   runtime->scroll_max);
      ED_region_tag_redraw(region);
      return OPERATOR_FINISHED;

    case AgentPanelHit::Eye:
      runtime->cards[card_index].expanded = !runtime->cards[card_index].expanded;
      ED_region_tag_redraw(region);
      return OPERATOR_FINISHED;

    case AgentPanelHit::Action: {
      /* Python owns the card mirror, so the removal goes back through its
       * operator rather than being written from here (the Director split:
       * native surfaces read RNA and invoke Python operators). */
      wmOperatorType *ot = WM_operatortype_find("MIXAR_OT_agent_panel_dismiss_card", true);
      if (ot == nullptr) {
        return OPERATOR_CANCELLED;
      }
      /* 5.2: this returns the PointerRNA instead of filling one in. */
      PointerRNA props = WM_operator_properties_create_ptr(ot);
      RNA_string_set(&props, "task_id", runtime->cards[card_index].task_id);
      WM_operator_name_call_ptr(
          C, ot, blender::wm::OpCallContext::ExecDefault, &props, nullptr);
      WM_operator_properties_free(&props);
      ED_region_tag_redraw(region);
      return OPERATOR_FINISHED;
    }

    case AgentPanelHit::Card:
      /* Inside a pill but on no control: eat it, so the click cannot fall
       * through and orbit the viewport underneath the card. */
      return OPERATOR_FINISHED;
  }
  return OPERATOR_PASS_THROUGH;
}

static void VIEW3D_OT_agent_panel_click(wmOperatorType *ot)
{
  ot->name = "Agent Panel Click";
  ot->idname = "VIEW3D_OT_agent_panel_click";
  ot->description = "Act on the parallel agent card under the cursor";

  ot->invoke = agent_panel_click_invoke;
  ot->poll = agent_panel_op_poll;

  ot->flag = 0;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Registration & Keymap
 * \{ */

void view3d_agent_panel_operatortypes()
{
  WM_operatortype_append(VIEW3D_OT_agent_panel_scroll);
  WM_operatortype_append(VIEW3D_OT_agent_panel_click);
  WM_operatortype_append(VIEW3D_OT_agent_panel_dismiss);
}

void view3d_agent_panel_keymap(wmKeyConfig *keyconf)
{
  /* This populates the DEFAULT keyconfig, whose items a GUI keyconfig preset
   * reload wipes. The bindings that survive are registered from Python in
   * `agent_panel/ui/keymap.py` — keep the two in sync. */
  wmKeyMap *keymap = WM_keymap_ensure(keyconf, "Agent Panel", SPACE_VIEW3D, RGN_TYPE_EXECUTE);
  wmKeyMapItem *kmi;

  /* PRESS, not CLICK: the cards have no drag gesture, so waiting out the
   * click timeout only adds latency and a dependence on release timing. */
  KeyMapItem_Params click_params{};
  click_params.type = LEFTMOUSE;
  click_params.value = KM_PRESS;
  WM_keymap_add_item(keymap, "VIEW3D_OT_agent_panel_click", &click_params);

  KeyMapItem_Params wheel_down_params{};
  wheel_down_params.type = WHEELDOWNMOUSE;
  wheel_down_params.value = KM_PRESS;
  kmi = WM_keymap_add_item(keymap, "VIEW3D_OT_agent_panel_scroll", &wheel_down_params);
  RNA_int_set(kmi->ptr, "delta", 1);

  KeyMapItem_Params wheel_up_params{};
  wheel_up_params.type = WHEELUPMOUSE;
  wheel_up_params.value = KM_PRESS;
  kmi = WM_keymap_add_item(keymap, "VIEW3D_OT_agent_panel_scroll", &wheel_up_params);
  RNA_int_set(kmi->ptr, "delta", -1);

  /* Trackpad two-finger scroll. Without this the panel is unscrollable on a
   * laptop — the gesture never arrives as a wheel event. */
  KeyMapItem_Params pan_params{};
  pan_params.type = MOUSEPAN;
  pan_params.value = KM_ANY;
  WM_keymap_add_item(keymap, "VIEW3D_OT_agent_panel_scroll", &pan_params);
}

/** \} */

}  // namespace blender
