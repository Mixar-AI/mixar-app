/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Mixar topbar: fit Engine's workspace tabs into the lane left of the
 * centred Zen/Engine switch.
 *
 * Runs after native layout, once the switch has its final rectangle. The
 * tabs first give back their extra pill padding (never below the native 10px
 * per side). When they still do not fit, the tabs past the lane are hidden
 * and listed by the overflow dropdown (`MIXAR_MT_workspace_overflow`, drawn
 * by the topbar header after `template_ID_tabs`). The New Workspace "+" is
 * always placed directly after the last visible tab, followed by that
 * dropdown, so the switch can never cover either of them. The active
 * workspace always keeps its tab: a new workspace is appended AND activated,
 * so it replaces the last tab that would otherwise have fitted.
 *
 * The hidden workspaces reach the dropdown's Python draw as context pointers
 * (`mixar_overflow_workspace_0`, `_1`, … in tab order) on its button.
 */

#include <algorithm>
#include <string>

#include "BKE_context.hh"
#include "BKE_screen.hh"

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_vector.hh"

#include "DNA_userdef_types.h"
#include "DNA_workspace_types.h"

#include "RNA_access.hh"

#include "WM_types.hh"

#include "UI_interface_c.hh"

#include "interface_intern.hh"
#include "interface_mixar_profile_card.hh"

namespace blender::ui {

namespace {

constexpr const char *OVERFLOW_MENU_IDNAME = "MIXAR_MT_workspace_overflow";
constexpr const char *OVERFLOW_CONTEXT_PREFIX = "mixar_overflow_workspace_";

/** Extra per-side pill padding a tab may give back (14px -> native 10px). */
constexpr float TAB_PADDING_TRIM_PX = 8.0f;

bool is_new_workspace_button(const Button &but)
{
  return but.optype && STREQ(but.optype->idname, "WORKSPACE_OT_add");
}

bool is_overflow_button(const Button &but)
{
  const MenuType *mt = button_menutype_get(&but);
  return mt && STREQ(mt->idname, OVERFLOW_MENU_IDNAME);
}

void place_x(Button &but, const float x)
{
  BLI_rctf_translate(&but.rect, x - but.rect.xmin, 0.0f);
}

/**
 * Which tabs stay visible when they overflow: the longest prefix whose
 * `width + gap` costs fit \a budget, with its trailing tabs given up so the
 * \a active tab (when past the prefix) fits too.
 */
Vector<bool> visible_tabs(const Span<float> widths,
                          const int active,
                          const float gap,
                          const float budget)
{
  Vector<bool> visible(widths.size(), false);
  /* Each tab costs its width plus the gap that follows it. */
  float used = 0.0f;
  int count = 0;
  while (count < widths.size() && used + widths[count] + gap <= budget) {
    used += widths[count] + gap;
    count++;
  }
  if (active >= count && active < widths.size()) {
    /* Give up trailing tabs until the active one fits in their place. */
    const float active_cost = widths[active] + gap;
    while (count > 0 && used + active_cost > budget) {
      count--;
      used -= widths[count] + gap;
    }
    if (used + active_cost <= budget) {
      visible[active] = true;
    }
  }
  for (int i = 0; i < count; i++) {
    visible[i] = true;
  }
  return visible;
}

}  // namespace

void mixar_topbar_fit_workspace_tabs(const bContext *C, Block *block, const float limit)
{
  Vector<Button *> tabs;
  Button *add = nullptr;
  Button *overflow = nullptr;
  for (Button &but : block->buttons()) {
    /* Test "+" first: `template_ID_tabs` builds it as a Tab button too
     * (`use_tab_but`), and counting it as a tab overflowed it away. */
    if (is_new_workspace_button(but)) {
      add = &but;
    }
    else if (but.type == ButtonType::Tab && but.custom_data) {
      tabs.append(&but);
    }
    else if (is_overflow_button(but)) {
      overflow = &but;
    }
  }
  if (tabs.is_empty()) {
    if (overflow) {
      overflow->flag |= UI_HIDDEN;
    }
    return;
  }

  const float start = tabs.first()->rect.xmin;
  const float add_width = add ? BLI_rctf_size_x(&add->rect) : 0.0f;
  const float overflow_width = overflow ? BLI_rctf_size_x(&overflow->rect) : 0.0f;
  /* The layout's own spacing between neighbouring buttons. */
  float gap = 0.0f;
  if (tabs.size() > 1) {
    gap = tabs[1]->rect.xmin - tabs[0]->rect.xmax;
  }
  else if (add) {
    gap = add->rect.xmin - tabs[0]->rect.xmax;
  }
  gap = std::max(gap, 0.0f);

  Vector<float> widths;
  float natural = add_width;
  for (const Button *tab : tabs) {
    widths.append(BLI_rctf_size_x(&tab->rect));
    natural += widths.last() + gap;
  }
  const float span = limit - start;

  /* Spend the added pill padding before hiding any tab. */
  if (natural > span) {
    const float trim = std::min(TAB_PADDING_TRIM_PX * UI_SCALE_FAC,
                                (natural - span) / float(tabs.size()));
    for (float &width : widths) {
      width -= trim;
    }
    natural -= trim * float(tabs.size());
  }

  const WorkSpace *workspace = C ? CTX_wm_workspace(C) : nullptr;
  int active = -1;
  for (const int i : tabs.index_range()) {
    if (workspace && tabs[i]->custom_data == static_cast<const void *>(&workspace->id)) {
      active = i;
    }
  }

  const bool overflows = natural > span;
  Vector<bool> visible(tabs.size(), true);
  if (overflows) {
    /* Reserve the "+" and the dropdown after the tabs that stay. */
    const float budget = span - add_width - (overflow ? gap + overflow_width : 0.0f);
    visible = visible_tabs(widths, active, gap, budget);
  }

  float x = start;
  for (const int i : tabs.index_range()) {
    Button &tab = *tabs[i];
    if (!visible[i]) {
      tab.flag |= UI_HIDDEN;
      continue;
    }
    place_x(tab, x);
    tab.rect.xmax = tab.rect.xmin + widths[i];
    x += widths[i] + gap;
  }
  if (add) {
    place_x(*add, x);
    if (add->rect.xmax > limit) {
      add->flag |= UI_HIDDEN;
    }
    x += add_width + gap;
  }
  if (!overflow) {
    return;
  }
  if (!overflows) {
    overflow->flag |= UI_HIDDEN;
    return;
  }
  place_x(*overflow, x);
  if (overflow->rect.xmax > limit) {
    overflow->flag |= UI_HIDDEN;
  }
  int index = 0;
  for (const int i : tabs.index_range()) {
    if (visible[i]) {
      continue;
    }
    const PointerRNA ptr = RNA_id_pointer_create(static_cast<ID *>(tabs[i]->custom_data));
    const std::string name = OVERFLOW_CONTEXT_PREFIX + std::to_string(index++);
    button_context_ptr_set(block, overflow, name, &ptr);
  }
}

}  // namespace blender::ui
