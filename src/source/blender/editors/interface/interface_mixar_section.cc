/* SPDX-FileCopyrightText: 2025 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Mixar custom UI widgets — helpers for styled layouts and controls.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "BLI_listbase.h"
#include "BLI_math_base.h"
#include "BLI_math_vector.h"
#include "BLI_rect.h"
#include "BLI_utildefines.h"

#include "BLT_translation.hh"

#include "BLF_api.hh"

#include "DNA_screen_types.h"
#include "DNA_userdef_types.h"

#include "BKE_screen.hh"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "UI_interface_c.hh"
#include "UI_resources.hh"
#include "UI_view2d.hh"

#include "interface_intern.hh"
#include "interface_mixar_profile_card.hh"
#include "interface_mixar_section.hh"

#include "UI_interface_layout.hh"

uiLayout *UI_layout_mixar_section(uiLayout *layout)
{
  uiLayout &box = layout->box();
  uiBlock *block = layout->block();

  /* Walk backwards through the block's buttons to find the Roundbox button
   * that was just created by box(). It should be the most recently added. */
  for (int i = int(block->buttons.size()) - 1; i >= 0; i--) {
    uiBut *but = block->buttons[i].get();
    if (but->type == ButType::Roundbox) {
      but->flag2 |= UI_BUT2_MIXAR_SECTION;
      break;
    }
  }

  return &box;
}

void UI_layout_mixar_mark_last_dropdown(uiLayout *layout)
{
  uiBlock *block = layout->block();

  /* Walk backwards to find the most recently created Menu button. */
  for (int i = int(block->buttons.size()) - 1; i >= 0; i--) {
    uiBut *but = block->buttons[i].get();
    if (ELEM(but->type, ButType::Menu, ButType::Block, ButType::Popover)) {
      but->flag2 |= UI_BUT2_MIXAR_DROPDOWN;
      break;
    }
  }
}

void UI_layout_mixar_mark_last_action(uiLayout *layout)
{
  uiBlock *block = layout->block();

  for (int i = int(block->buttons.size()) - 1; i >= 0; i--) {
    uiBut *but = block->buttons[i].get();
    if (but->type == ButType::But) {
      but->flag2 |= UI_BUT2_MIXAR_ACTION;
      break;
    }
  }
}

void UI_layout_mixar_mark_last_toggle(uiLayout *layout)
{
  uiBlock *block = layout->block();

  for (int i = int(block->buttons.size()) - 1; i >= 0; i--) {
    uiBut *but = block->buttons[i].get();
    if (ELEM(but->type, ButType::Checkbox, ButType::CheckboxN)) {
      but->flag2 |= UI_BUT2_MIXAR_TOGGLE;
      break;
    }
  }
}

void UI_layout_mixar_mark_last_input(uiLayout *layout)
{
  uiBlock *block = layout->block();

  for (int i = int(block->buttons.size()) - 1; i >= 0; i--) {
    uiBut *but = block->buttons[i].get();
    if (but->type == ButType::Text) {
      but->flag2 |= UI_BUT2_MIXAR_INPUT;
      break;
    }
  }
}

/* -------------------------------------------------------------------- */
/* Profile-card element reuse                                            */

/* Card-styled surfaces built from Python (the AI Provider Settings
 * dialog) tag ordinary layout items with the profile card's element
 * kinds so they share its painters. These mirror the private
 * `mark_last` in `interface_mixar_profile_card.cc`; they live here with
 * the other mark-last helpers to keep that file inside the size rule. */

void UI_layout_mixar_card_tag_last(uiLayout *layout,
                                   const MixarCardElement element,
                                   const float payload)
{
  uiBlock *block = layout->block();
  if (block->buttons.is_empty()) {
    return;
  }
  uiBut *but = block->buttons[block->buttons.size() - 1].get();
  UI_BUT2_MIXAR_CARD_SET(but);
  /* `hardmin`/`hardmax` are inert on the label and operator buttons
   * tagged here — neither carries a data pointer or RNA property (see
   * the rationale on `mark_last` in `interface_mixar_profile_card.cc`). */
  but->hardmin = float(int(element));
  but->hardmax = payload;
}

void UI_layout_mixar_card_style_last_button(uiLayout *layout,
                                            const MixarCardElement element,
                                            const bool active_default)
{
  if (!UI_mixar_card_element_is_button(element)) {
    /* A text kind on a clickable rect would paint chrome-less glyphs
     * over a live hit area — refuse rather than draw a broken button. */
    return;
  }
  uiBlock *block = layout->block();
  for (int i = int(block->buttons.size()) - 1; i >= 0; i--) {
    uiBut *but = block->buttons[i].get();
    if (but->type != ButType::But) {
      continue;
    }
    UI_BUT2_MIXAR_CARD_SET(but);
    but->hardmin = float(int(element));
    but->hardmax = 0.0f; /* MixarCardIcon::None — the painter centres the label. */
    /* Set *or clear*: `template_popup_confirm` hands its cancel button
     * the active-default flag when nothing else holds it yet, so a
     * dialog styling that button afterwards must be able to take the
     * flag away again and give it to its real primary action. The flag
     * is also the native OK/Cancel suppression contract — see
     * #wm_block_dialog_create. */
    if (active_default) {
      UI_but_flag_enable(but, UI_BUT_ACTIVE_DEFAULT);
    }
    else {
      UI_but_flag_disable(but, UI_BUT_ACTIVE_DEFAULT);
    }
    break;
  }
}

/* -------------------------------------------------------------------- */
/* Mixar Custom Panel Category Tabs                                      */

/* Convert uchar[4] (0-255) to float[4] (0.0-1.0). */
static void ubyte4_to_float4(float dst[4], const unsigned char src[4])
{
  dst[0] = float(src[0]) / 255.0f;
  dst[1] = float(src[1]) / 255.0f;
  dst[2] = float(src[2]) / 255.0f;
  dst[3] = float(src[3]) / 255.0f;
}

/* Padding constants */
#define MIXAR_TAB_PAD_TEXT 8.0f
#define MIXAR_TAB_PAD_BETWEEN 6.0f

void UI_panel_category_draw_all_mixar(ARegion *region, const char *category_id_active)
{
  const bool is_left = RGN_ALIGN_ENUM_FROM_MASK(region->alignment) != RGN_ALIGN_RIGHT;
  View2D *v2d = &region->v2d;
  const uiStyle *style = UI_style_get();
  const uiFontStyle *fstyle = &style->widget;
  UI_fontstyle_set(fstyle);
  const int fontid = fstyle->uifont_id;
  float fstyle_points = fstyle->points;
  const float aspect = BLI_listbase_is_empty(&region->runtime->uiblocks) ?
                            1.0f :
                            ((uiBlock *)region->runtime->uiblocks.first)->aspect;
  const float zoom = 1.0f / aspect;
  const float dpi_fac = UI_SCALE_FAC;
  const int px = U.pixelsize;

  /* Read all colors from the theme (space_mixie in bTheme). */
  const bTheme *btheme = UI_GetTheme();
  const ThemeSpace *ts = &btheme->space_mixie;

  float col_accent[4], col_strip_bg[4], col_inactive[4];
  float col_text_active[4], col_text_inactive[4];
  float col_glow[4], col_highlight[4], col_indicator[4];

  ubyte4_to_float4(col_accent, ts->mixar_tab_accent);
  ubyte4_to_float4(col_strip_bg, ts->mixar_tab_strip_bg);
  ubyte4_to_float4(col_inactive, ts->mixar_tab_inactive);
  ubyte4_to_float4(col_text_active, ts->mixar_tab_text_active);
  ubyte4_to_float4(col_text_inactive, ts->mixar_tab_text_inactive);
  ubyte4_to_float4(col_glow, ts->mixar_tab_glow);
  ubyte4_to_float4(col_highlight, ts->mixar_tab_highlight);
  ubyte4_to_float4(col_indicator, ts->mixar_tab_indicator);

  /* Fallback defaults when theme colors are uninitialized (all zero from old .blend files). */
  if (col_accent[0] == 0.0f && col_accent[1] == 0.0f && col_accent[2] == 0.0f) {
    col_accent[0] = 0.0f/255; col_accent[1] = 192.0f/255; col_accent[2] = 199.0f/255; col_accent[3] = 1.0f; /* #00C0C7 accent */
    col_strip_bg[0] = 0.08f; col_strip_bg[1] = 0.08f; col_strip_bg[2] = 0.10f; col_strip_bg[3] = 0.95f;
    col_inactive[0] = 0.14f; col_inactive[1] = 0.14f; col_inactive[2] = 0.16f; col_inactive[3] = 0.6f;
    col_text_active[0] = col_text_active[1] = col_text_active[2] = col_text_active[3] = 1.0f;
    col_text_inactive[0] = col_text_inactive[1] = 0.627f; col_text_inactive[2] = 0.667f; col_text_inactive[3] = 1.0f;
    col_glow[0] = 112.0f/255; col_glow[1] = 198.0f/255; col_glow[2] = 45.0f/255; col_glow[3] = 0.15f;
    col_highlight[0] = col_highlight[1] = col_highlight[2] = 1.0f; col_highlight[3] = 0.18f;
    col_indicator[0] = col_indicator[1] = col_indicator[2] = 1.0f; col_indicator[3] = 0.4f;
  }

  /* Wider tabs than default for more breathing room. */
  const int category_tabs_width = round_fl_to_int(UI_PANEL_CATEGORY_MARGIN_WIDTH * zoom * 1.15f);
  const int tab_v_pad_text = round_fl_to_int(MIXAR_TAB_PAD_TEXT * dpi_fac * zoom) + 2 * px;
  const int tab_v_pad = round_fl_to_int(MIXAR_TAB_PAD_BETWEEN * dpi_fac * zoom);

  /* Tab shape: fully rounded pill. */
  const float tab_radius = float(category_tabs_width) * 0.38f;

  BLF_enable(fontid, BLF_ROTATION);
  BLF_rotation(fontid, is_left ? M_PI_2 : -M_PI_2);
  ui_fontscale(&fstyle_points, aspect);
  BLF_size(fontid, fstyle_points * UI_SCALE_FAC);

  /* Tab strip position. */
  const int rct_xmin = is_left ? v2d->mask.xmin + 3 : (v2d->mask.xmax - category_tabs_width);
  const int rct_xmax = is_left ? v2d->mask.xmin + category_tabs_width : (v2d->mask.xmax - 3);

  int y_ofs = tab_v_pad;

  /* Calculate tab rectangles. */
  LISTBASE_FOREACH (PanelCategoryDyn *, pc_dyn, &region->runtime->panels_category) {
    rcti *rct = &pc_dyn->rect;
    const char *category_id_draw = IFACE_(pc_dyn->idname);
    const int category_width = round_fl_to_int(
        BLF_width(fontid, category_id_draw, BLF_DRAW_STR_DUMMY_MAX));

    rct->xmin = rct_xmin;
    rct->xmax = rct_xmax;
    rct->ymin = v2d->mask.ymax - (y_ofs + category_width + (tab_v_pad_text * 2));
    rct->ymax = v2d->mask.ymax - y_ofs;

    y_ofs += category_width + tab_v_pad + (tab_v_pad_text * 2);
  }

  /* Scrolling. */
  const int max_scroll = std::max(y_ofs - BLI_rcti_size_y(&v2d->mask), 0);
  const int scroll = std::clamp(region->category_scroll, 0, max_scroll);
  region->category_scroll = scroll;
  LISTBASE_FOREACH (PanelCategoryDyn *, pc_dyn, &region->runtime->panels_category) {
    rcti *rct = &pc_dyn->rect;
    rct->ymin += scroll;
    rct->ymax += scroll;
  }

  /* --- Draw background strip --- */
  GPU_blend(GPU_BLEND_ALPHA);

  {
    const rctf bg_rect = {
        float(is_left ? v2d->mask.xmin : v2d->mask.xmax - category_tabs_width),
        float(is_left ? v2d->mask.xmin + category_tabs_width : v2d->mask.xmax + 1),
        float(v2d->mask.ymin),
        float(v2d->mask.ymax),
    };
    UI_draw_roundbox_corner_set(UI_CNR_NONE);
    UI_draw_roundbox_4fv(&bg_rect, true, 0.0f, col_strip_bg);

    /* Subtle accent line along the panel-facing edge. */
    const float edge_color[4] = {col_accent[0], col_accent[1], col_accent[2], 0.12f};
    const float edge_w = 1.5f * dpi_fac;
    rctf edge_rect;
    if (is_left) {
      edge_rect = {float(rct_xmax) - edge_w, float(rct_xmax),
                    float(v2d->mask.ymin), float(v2d->mask.ymax)};
    }
    else {
      edge_rect = {float(rct_xmin), float(rct_xmin) + edge_w,
                    float(v2d->mask.ymin), float(v2d->mask.ymax)};
    }
    UI_draw_roundbox_4fv(&edge_rect, true, 0.0f, edge_color);
  }

  /* If area is too small, don't show any active. */
  const bool too_narrow = BLI_rcti_size_x(&region->winrct) <=
                          int(UI_PANEL_CATEGORY_MIN_WIDTH * UI_SCALE_FAC / aspect);

  GPU_line_smooth(true);

  /* --- Draw each tab --- */
  LISTBASE_FOREACH (PanelCategoryDyn *, pc_dyn, &region->runtime->panels_category) {
    const rcti *rct = &pc_dyn->rect;

    if (rct->ymin > v2d->mask.ymax) {
      continue;
    }
    if (rct->ymax < v2d->mask.ymin) {
      break;
    }

    const char *category_id = pc_dyn->idname;
    const char *category_id_draw = IFACE_(category_id);
    const size_t category_draw_len = BLF_DRAW_STR_DUMMY_MAX;
    const bool is_active = !too_narrow && STREQ(category_id, category_id_active);

    /* Inset the tab slightly from the strip edges for padding. */
    const float inset = 3.0f * dpi_fac;
    rctf tab_rect;
    tab_rect.xmin = float(rct->xmin) + inset;
    tab_rect.xmax = float(rct->xmax) - inset;
    tab_rect.ymin = float(rct->ymin);
    tab_rect.ymax = float(rct->ymax);

    if (is_active) {
      /* Active tab: --mx-accent-soft fill (#00C0C7 @ ~13%) + teal outline;
       * the teal label (drawn below) carries the accent. Design-agent spec.
       * col_glow / col_highlight are intentionally left unused. */
      const float active_bg[4] = {0.0f, 192.0f / 255.0f, 199.0f / 255.0f, 0.13f};
      UI_draw_roundbox_corner_set(UI_CNR_ALL);
      UI_draw_roundbox_4fv(&tab_rect, true, tab_radius, active_bg);

      const float active_outline[4] = {col_accent[0], col_accent[1], col_accent[2], 0.45f};
      UI_draw_roundbox_4fv(&tab_rect, false, tab_radius, active_outline);
    }
    else {
      /* --- Inactive tab: subtle dark fill --- */
      UI_draw_roundbox_corner_set(UI_CNR_ALL);
      UI_draw_roundbox_4fv(&tab_rect, true, tab_radius, col_inactive);

      /* Very subtle outline. */
      const float outline_color[4] = {1.0f, 1.0f, 1.0f, 0.04f};
      UI_draw_roundbox_4fv(&tab_rect, false, tab_radius, outline_color);
    }

    /* --- Tab text --- */
    const int text_v_ofs = round_fl_to_int(float(rct_xmax - rct_xmin) * 0.5f);
    const int text_size_offset = round_fl_to_int(fstyle_points * UI_SCALE_FAC * 0.35f);

    BLF_position(fontid,
                 is_left ? rct->xmax - text_v_ofs + text_size_offset :
                           rct->xmin + text_v_ofs - text_size_offset,
                 is_left ? rct->ymin + tab_v_pad_text : rct->ymax - tab_v_pad_text,
                 0.0f);

    if (is_active) {
      /* Teal active label (design-system accent) on the dark tab. */
      const uchar text_col[4] = {uchar(col_accent[0] * 255.0f),
                                  uchar(col_accent[1] * 255.0f),
                                  uchar(col_accent[2] * 255.0f),
                                  255};
      BLF_color4ubv(fontid, text_col);
    }
    else {
      const uchar text_col[4] = {uchar(col_text_inactive[0] * 255.0f),
                                  uchar(col_text_inactive[1] * 255.0f),
                                  uchar(col_text_inactive[2] * 255.0f),
                                  255};
      BLF_color4ubv(fontid, text_col);
    }

    if (fstyle->shadow) {
      BLF_enable(fontid, BLF_SHADOW);
      const float shadow_color[4] = {0.0f, 0.0f, 0.0f, 0.6f};
      BLF_shadow(fontid, FontShadowType(fstyle->shadow), shadow_color);
      BLF_shadow_offset(fontid, fstyle->shadx, fstyle->shady);
    }

    BLF_draw(fontid, category_id_draw, category_draw_len);

    if (fstyle->shadow) {
      BLF_disable(fontid, BLF_SHADOW);
    }

    /* Extend hit area to region edge. */
    if (is_left) {
      pc_dyn->rect.xmin = v2d->mask.xmin;
    }
    else {
      pc_dyn->rect.xmax = v2d->mask.xmax;
    }
  }

  GPU_blend(GPU_BLEND_NONE);
  GPU_line_smooth(false);
  BLF_disable(fontid, BLF_ROTATION);
}

#undef MIXAR_TAB_PAD_TEXT
#undef MIXAR_TAB_PAD_BETWEEN
