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

#include "BLI_map.hh"
#include "BLI_string.h"
#include "BLI_vector.hh"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "UI_interface_c.hh"
#include "UI_resources.hh"
#include "UI_view2d.hh"

#include "interface_intern.hh"
#include "interface_mixar_section.hh"

#include "UI_interface_layout.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui {

Layout *UI_layout_mixar_section(Layout *layout)
{
  Layout &box = layout->box();
  Block *block = layout->block();

  /* Walk backwards through the block's buttons to find the Roundbox button
   * that was just created by box(). It should be the most recently added. */
  for (int i = int(block->buttons_ptrs.size()) - 1; i >= 0; i--) {
    Button *but = block->buttons_ptrs[i].get();
    if (but->type == ButtonType::Roundbox) {
      but->flag2 |= UI_BUT2_MIXAR_SECTION;
      break;
    }
  }

  return &box;
}

void UI_layout_mixar_mark_last_dropdown(Layout *layout)
{
  Block *block = layout->block();

  /* Walk backwards to find the most recently created Menu button. */
  for (int i = int(block->buttons_ptrs.size()) - 1; i >= 0; i--) {
    Button *but = block->buttons_ptrs[i].get();
    if (ELEM(but->type, ButtonType::Menu, ButtonType::Block, ButtonType::Popover)) {
      but->flag2 |= UI_BUT2_MIXAR_DROPDOWN;
      break;
    }
  }
}

void UI_layout_mixar_mark_last_action(Layout *layout)
{
  Block *block = layout->block();

  for (int i = int(block->buttons_ptrs.size()) - 1; i >= 0; i--) {
    Button *but = block->buttons_ptrs[i].get();
    if (but->type == ButtonType::But) {
      but->flag2 |= UI_BUT2_MIXAR_ACTION;
      break;
    }
  }
}

void UI_layout_mixar_mark_last_toggle(Layout *layout)
{
  Block *block = layout->block();

  for (int i = int(block->buttons_ptrs.size()) - 1; i >= 0; i--) {
    Button *but = block->buttons_ptrs[i].get();
    if (ELEM(but->type, ButtonType::Checkbox, ButtonType::CheckboxN)) {
      but->flag2 |= UI_BUT2_MIXAR_TOGGLE;
      break;
    }
  }
}

void UI_layout_mixar_mark_last_input(Layout *layout)
{
  Block *block = layout->block();

  for (int i = int(block->buttons_ptrs.size()) - 1; i >= 0; i--) {
    Button *but = block->buttons_ptrs[i].get();
    if (but->type == ButtonType::Text) {
      but->flag2 |= UI_BUT2_MIXAR_INPUT;
      break;
    }
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

/* -------------------------------------------------------------------- */
/* Mixar tab hit-rects.
 *
 * Blender 5.2 removed `PanelCategoryDyn::rect` (upstream tabs became real
 * buttons), so the rects of the Mixar-drawn strip are recorded here at draw
 * time and hit-tested by the MIXAR hook in interface_panel.cc. Entries are
 * overwritten on every draw; a stale entry for a freed region can only be
 * read if a click arrives for a region that never drew, which cannot
 * happen for a visible strip. */

struct MixarCategoryTabRect {
  char idname[64];
  rcti rect;
};

static Map<const ARegion *, Vector<MixarCategoryTabRect>> &mixar_category_tab_rects()
{
  static Map<const ARegion *, Vector<MixarCategoryTabRect>> map;
  return map;
}

const char *UI_mixar_panel_category_find_at(const ARegion *region, const int mval[2])
{
  const Vector<MixarCategoryTabRect> *tabs = mixar_category_tab_rects().lookup_ptr(region);
  if (tabs == nullptr) {
    return nullptr;
  }
  for (const MixarCategoryTabRect &tab : *tabs) {
    if (BLI_rcti_isect_pt(&tab.rect, mval[0], mval[1])) {
      return tab.idname;
    }
  }
  return nullptr;
}

void UI_panel_category_draw_all_mixar(ARegion *region, const char *category_id_active)
{
  Vector<MixarCategoryTabRect> tab_rects;
  const bool is_left = RGN_ALIGN_ENUM_FROM_MASK(region->alignment) != RGN_ALIGN_RIGHT;
  View2D *v2d = &region->v2d;
  const uiStyle *style = style_get();
  const uiFontStyle *fstyle = &style->widget;
  fontstyle_set(fstyle);
  const int fontid = fstyle->uifont_id;
  float fstyle_points = fstyle->points;
  const float aspect = BLI_listbase_is_empty(&region->runtime->uiblocks) ?
                            1.0f :
                            ((Block *)region->runtime->uiblocks.first)->aspect;
  const float zoom = 1.0f / aspect;
  const float dpi_fac = UI_SCALE_FAC;
  const int px = U.pixelsize;

  /* Read all colors from the theme (space_mixie in bTheme). */
  const bTheme *btheme = theme::theme_get();
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
  fontscale(&fstyle_points, aspect);
  BLF_size(fontid, fstyle_points * UI_SCALE_FAC);

  /* Tab strip position. */
  const int rct_xmin = is_left ? v2d->mask.xmin + 3 : (v2d->mask.xmax - category_tabs_width);
  const int rct_xmax = is_left ? v2d->mask.xmin + category_tabs_width : (v2d->mask.xmax - 3);

  int y_ofs = tab_v_pad;

  /* Calculate tab rectangles. */
  for (PanelCategoryDyn &pc_dyn_iter : region->runtime->panels_category) {
    PanelCategoryDyn *pc_dyn = &pc_dyn_iter;
    MixarCategoryTabRect tab = {};
    STRNCPY(tab.idname, pc_dyn->idname);
    rcti *rct = &tab.rect;
    const char *category_id_draw = IFACE_(pc_dyn->idname);
    const int category_width = round_fl_to_int(
        BLF_width(fontid, category_id_draw, BLF_DRAW_STR_DUMMY_MAX));

    rct->xmin = rct_xmin;
    rct->xmax = rct_xmax;
    rct->ymin = v2d->mask.ymax - (y_ofs + category_width + (tab_v_pad_text * 2));
    rct->ymax = v2d->mask.ymax - y_ofs;

    y_ofs += category_width + tab_v_pad + (tab_v_pad_text * 2);
    tab_rects.append(tab);
  }

  /* Scrolling. */
  const int max_scroll = std::max(y_ofs - BLI_rcti_size_y(&v2d->mask), 0);
  const int scroll = std::clamp(region->category_scroll, 0, max_scroll);
  region->category_scroll = scroll;
  for (MixarCategoryTabRect &tab : tab_rects) {
    tab.rect.ymin += scroll;
    tab.rect.ymax += scroll;
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
    draw_roundbox_corner_set(CNR_NONE);
    draw_roundbox_4fv(&bg_rect, true, 0.0f, col_strip_bg);

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
    draw_roundbox_4fv(&edge_rect, true, 0.0f, edge_color);
  }

  /* If area is too small, don't show any active. */
  const bool too_narrow = BLI_rcti_size_x(&region->winrct) <=
                          int(UI_PANEL_CATEGORY_MIN_WIDTH * UI_SCALE_FAC / aspect);

  GPU_line_smooth(true);

  /* --- Draw each tab --- */
  int tab_index = -1;
  for (PanelCategoryDyn &pc_dyn_iter : region->runtime->panels_category) {
    PanelCategoryDyn *pc_dyn = &pc_dyn_iter;
    tab_index++;
    const rcti *rct = &tab_rects[tab_index].rect;

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
      draw_roundbox_corner_set(CNR_ALL);
      draw_roundbox_4fv(&tab_rect, true, tab_radius, active_bg);

      const float active_outline[4] = {col_accent[0], col_accent[1], col_accent[2], 0.45f};
      draw_roundbox_4fv(&tab_rect, false, tab_radius, active_outline);
    }
    else {
      /* --- Inactive tab: subtle dark fill --- */
      draw_roundbox_corner_set(CNR_ALL);
      draw_roundbox_4fv(&tab_rect, true, tab_radius, col_inactive);

      /* Very subtle outline. */
      const float outline_color[4] = {1.0f, 1.0f, 1.0f, 0.04f};
      draw_roundbox_4fv(&tab_rect, false, tab_radius, outline_color);
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
      tab_rects[tab_index].rect.xmin = v2d->mask.xmin;
    }
    else {
      tab_rects[tab_index].rect.xmax = v2d->mask.xmax;
    }
  }

  mixar_category_tab_rects().add_overwrite(region, std::move(tab_rects));

  GPU_blend(GPU_BLEND_NONE);
  GPU_line_smooth(false);
  BLF_disable(fontid, BLF_ROTATION);
}

#undef MIXAR_TAB_PAD_TEXT
#undef MIXAR_TAB_PAD_BETWEEN
}  // namespace blender::ui
