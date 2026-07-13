/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie_chat
 *
 * Floating "agent bubble" popup overlay.
 *
 * Renders a persistent popup block (UI_BLOCK_KEEP_OPEN) on top of every
 * editor in the active window. The popup is window-level, so it doesn't
 * clip at editor region boundaries the way a Python draw_handler would.
 *
 * Content is supplied by a Python menu type (MIXIE_CHAT_MT_agent_bubble)
 * so the actual layout — input field, send button, status indicator —
 * is authored in Python with the same UILayout API used everywhere
 * else, including the existing draw_multiline_text_input wrapper from
 * common/utils/ui_utils.py.
 */

#include "BKE_context.hh"

#include "BLT_translation.hh"

#include "UI_interface.hh"
#include "UI_interface_layout.hh"
#include "UI_resources.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "wm.hh"

#include "mixie_chat_intern.hh"

/* -------------------------------------------------------------------- */
/** \name Agent Bubble Popup Block
 * \{ */

static uiBlock *mixie_chat_block_agent_bubble_create(bContext *C,
                                                     ARegion *region,
                                                     void * /*arg*/)
{
  const uiStyle *style = UI_style_get_dpi();

  uiBlock *block = UI_block_begin(
      C, region, "agent_bubble", blender::ui::EmbossType::Emboss);

  /* Persistent popup: stays open across redraws until we explicitly
   * close it. UI_BLOCK_NO_WIN_CLIP keeps the popup intact during
   * window-resize transients. */
  UI_block_flag_enable(block, UI_BLOCK_LOOP | UI_BLOCK_KEEP_OPEN | UI_BLOCK_NO_WIN_CLIP);
  UI_block_theme_style_set(block, UI_BLOCK_THEME_STYLE_POPUP);

  /* Width sized off the DPI-aware widget grid so it scales with the
   * user's interface scaling. 42 widget-points is ~30% narrower than
   * the original 60 — keeps the composer compact instead of stretching
   * across most of the viewport. */
  const int bubble_width = style->widget.points * 42 * UI_SCALE_FAC;

  uiLayout &layout = blender::ui::block_layout(block,
                                               blender::ui::LayoutDirection::Vertical,
                                               blender::ui::LayoutType::Panel,
                                               0,
                                               0,
                                               bubble_width,
                                               UI_SCALE_FAC * 16,
                                               0,
                                               style);

  /* Defer the actual layout to a Python menu so the bubble's UI lives
   * alongside the rest of the chat UI code and can use shared helpers
   * like draw_multiline_text_input. */
  MenuType *mt = WM_menutype_find("MIXIE_CHAT_MT_agent_bubble", true);
  if (mt) {
    UI_menutype_draw(C, mt, &layout);
  }
  else {
    /* Fallback: render a small placeholder so we see SOMETHING when the
     * Python menu hasn't loaded yet. Without this, an empty uiBlock
     * collapses to zero size and the popup is effectively invisible —
     * which makes the bubble look broken. */
    layout.label("Mixar agent bubble loading…", ICON_INFO);
  }

  UI_block_bounds_set_centered(block, 6 * UI_SCALE_FAC);

  return block;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Operator
 * \{ */

static wmOperatorStatus mixie_chat_agent_bubble_show_invoke(bContext *C,
                                                             wmOperator * /*op*/,
                                                             const wmEvent * /*event*/)
{
  UI_popup_block_invoke(C, mixie_chat_block_agent_bubble_create, nullptr, nullptr);
  return OPERATOR_FINISHED;
}

void MIXIE_CHAT_OT_agent_bubble_show(wmOperatorType *ot)
{
  ot->name = "Show Agent Bubble";
  /* idname uses Blender's C-style convention (CATEGORY_OT_name). Blender
   * auto-converts to the dotted Python form (mixie_chat.agent_bubble_show)
   * for bpy.ops calls and Search. Using the dotted form directly here
   * makes the operator unfindable from Python — that's the silent
   * failure mode that took multiple iterations to diagnose. */
  ot->idname = "MIXIE_CHAT_OT_agent_bubble_show";
  ot->description =
      "Open the floating agent bubble overlay that lets the user chat with the AI agent "
      "from anywhere in the Mixar interface";

  ot->invoke = mixie_chat_agent_bubble_show_invoke;
  /* No poll — the operator is universally callable. WM_operator_winactive
   * sometimes filtered the operator out of F3 Search in editor contexts
   * where CTX_wm_window resolves through a temp override; without a poll
   * the operator always appears in Search and bpy.ops calls always
   * reach the invoke. */
}

/** \} */
