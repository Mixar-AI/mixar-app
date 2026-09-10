/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Implementation of the island pane kit — see agent_ui_pane_kit.hh for the
 * vocabulary, sources and the layout contract.
 */

#include <algorithm>
#include <cstring>
#include <string>

#include "MEM_guardedalloc.h"

#include "BLF_api.hh"

#include "BIF_glutil.hh"

#include "BKE_context.hh"
#include "BKE_image.hh"

#include "BLI_rect.h"
#include "BLI_string.h"

#include "DNA_image_types.h"
#include "DNA_scene_types.h"

#include "GPU_shader_builtin.hh"
#include "GPU_state.hh"

#include "IMB_imbuf.hh"
#include "IMB_imbuf_types.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_mixar.hh"
#include "UI_interface_c.hh"

#include "agent_ui_icons.hh"
#include "agent_ui_pane_kit.hh"
#include "agent_ui_theme.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Primitives
 * \{ */

void pane_fill_round(const rctf *rect, const float radius, const float col[4])
{
  ui::mixar_fill_round(*rect, radius, col);
}

float pane_text_width(const char *text, const float size)
{
  return ui::mixar_text_width(text, size);
}

void pane_label_left(
    const char *text, const float x, const float cy, const float size, const float col[4])
{
  ui::mixar_label_left(text, x, cy, size, col);
}

void pane_label_centre(
    const char *text, const float cx, const float cy, const float size, const float col[4])
{
  pane_label_left(text, cx - pane_text_width(text, size) * 0.5f, cy, size, col);
}

void pane_label_right(
    const char *text, const float x, const float cy, const float size, const float col[4])
{
  pane_label_left(text, x - pane_text_width(text, size), cy, size, col);
}

void pane_fit_text(char *text, const float max_w, const float size)
{
  const size_t capacity = strlen(text) + 1;
  const std::string fitted = ui::mixar_fit_text(text, max_w, size);
  /* This compatibility API only shrinks the caller's buffer. */
  if (fitted.size() < capacity) {
    memcpy(text, fitted.c_str(), fitted.size() + 1);
  }
  else {
    text[0] = '\0';
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Composites
 * \{ */

void pane_wash_paint(const rctf &panel, const float u)
{
  const float top[4] = PANE_COL_WASH_TOP;
  const float bottom[4] = PANE_COL_WASH_BOTTOM;
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  /* Vertical stand-in for the frames' near-vertical gradient; the diagonal
   * component is imperceptible at this delta. */
  ui::draw_roundbox_4fv_ex(&panel, bottom, top, 1.0f, nullptr, 0.0f, AGENT_PANEL_RADIUS * u);
}

rctf pane_prompt_box_rect(const rctf &panel, const float strip_bottom_y, const float u)
{
  rctf box;
  box.xmin = panel.xmin + PANE_BOX_INSET * u;
  box.xmax = panel.xmax - PANE_BOX_INSET * u;
  box.ymax = strip_bottom_y - PANE_BOX_GAP * u;
  box.ymin = panel.ymin + PANE_BOX_INSET * u;
  /* Never below the region edge: the panel's bottom inset lives inside the
   * TOOLS card-foot band, so panel.ymin can be slightly NEGATIVE in this
   * region's coordinates — a box (and its bottom row) placed from it then
   * paints below y=0 and is scissored off. 2px keeps the box's rounded foot
   * visible in every geometry. */
  if (box.ymin < 2.0f) {
    box.ymin = 2.0f;
  }
  if (box.ymax < box.ymin) {
    box.ymax = box.ymin;
  }
  return box;
}

float pane_params_floor(const rctf &panel, const float u)
{
  /* Mirrors pane_prompt_box_rect's own bottom clamp, or the floor promises a
   * box the box rect cannot deliver. */
  const float box_bottom = std::max(panel.ymin + PANE_BOX_INSET * u, 2.0f);
  return box_bottom + (PANE_BOX_MIN_H + PANE_BOX_GAP) * u;
}

bool pane_prompt_fits(const rctf &box, const float u)
{
  return BLI_rctf_size_y(&box) >= PANE_BOX_MIN_H * u;
}

rctf pane_prompt_field_rect(const rctf &box, const float u)
{
  /* The field IS the whole box — the design's prompt area. Blender's
   * multiline text path (Text + ui::BUT_TEXTEDIT_UPDATE + tall rect) renders
   * top-left with a text-height caret, so no strip-sizing is needed; a
   * top-strip variant was tried and read as "just a thin bar". */
  UNUSED_VARS(u);
  return box;
}

void pane_prompt_box_paint(const rctf &box, const float u)
{
  if (BLI_rctf_size_y(&box) <= 1.0f) {
    return;
  }
  const float col[4] = PANE_COL_BOX;
  pane_fill_round(&box, PANE_BOX_RADIUS * u, col);
}

float pane_bottom_row_ymin(const rctf &box, const float u)
{
  const float y = box.ymin + PANE_BOTTOM_UP * u;
  /* Clamp INSIDE the box: unclamped, a short box pushed the PANE_ROW_H row up
   * through its top, so Upload and Generate floated over the params strip —
   * and because the OPS block wins overlapping clicks, the params beneath
   * them became unreachable. */
  const float y_top_limit = box.ymax - PANE_ROW_H * u;
  return std::max(box.ymin, std::min(y, y_top_limit));
}

rctf pane_generate_rect(const rctf &box, const float u)
{
  rctf rect;
  rect.xmax = box.xmax - PANE_BOTTOM_IN_R * u;
  rect.xmin = rect.xmax - PANE_GENERATE_W * u;
  rect.ymin = pane_bottom_row_ymin(box, u);
  /* A box shorter than one row still cannot spill over its own top edge. */
  rect.ymax = std::min(rect.ymin + PANE_ROW_H * u, box.ymax);
  return rect;
}

float pane_action_chip_w(const char *label, const bool with_icon, const float u)
{
  const float pad = PANE_CHIP_PAD_X * u;
  const float icon = with_icon ? (AGENT_CHIP_ICON * u + AGENT_CHIP_ICON_GAP * u) : 0.0f;
  return pad + icon + pane_text_width(label, PANE_FONT * u) + pad;
}

float pane_dropdown_chip_w(const char *label, const float u)
{
  const float pad = PANE_CHIP_PAD_X * u;
  const float chev = AGENT_CHIP_ICON * u * 0.8f;
  return pad + pane_text_width(label, PANE_FONT * u) + 10.0f * u + chev + pad * 0.75f;
}

rctf pane_segmented_layout(const float x,
                           const float y_top,
                           const char *const *labels,
                           const int count,
                           const float u,
                           rctf *r_segs)
{
  const float pad = 14.0f * u;
  float sx = x;
  for (int i = 0; i < count; i++) {
    const float w = pane_text_width(labels[i], PANE_FONT * u) + pad * 2.0f;
    r_segs[i].xmin = sx;
    r_segs[i].xmax = sx + w;
    r_segs[i].ymax = y_top;
    r_segs[i].ymin = y_top - PANE_ROW_H * u;
    sx = r_segs[i].xmax;
  }
  rctf track;
  track.xmin = x;
  track.xmax = sx;
  track.ymax = y_top;
  track.ymin = y_top - PANE_ROW_H * u;
  return track;
}

float pane_onoff_chip_w(const char *label, const float u)
{
  const float font = PANE_FONT * u;
  return PANE_CHIP_PAD_X * u + pane_text_width(label, font) + 12.0f * u +
         pane_text_width("ON", font) + 20.0f * u + pane_text_width("OFF", font) + 20.0f * u +
         PANE_CHIP_PAD_X * u * 0.75f;
}

/** \} */
/* -------------------------------------------------------------------- */
/** \name Owned tooltips
 * \{ */

void pane_but_tooltip_owned(ui::Button *but, const char *text)
{
  ui::mixar_button_tooltip_owned(but, text);
}

/** \} */

}  // namespace blender
