/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * The model chip. See agent_ui_provider.hh.
 */

#include "agent_ui_provider.hh"

#include <algorithm>
#include <cstring>
#include <string>

#include "MEM_guardedalloc.h"

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_string_utf8.h"

#include "BLF_api.hh"

#include "BLT_translation.hh"

#include "BKE_context.hh"

#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_mixar.hh"
#include "UI_resources.hh"

#include "agent_ui_chip_fit.hh"
#include "agent_ui_draw.hh"
#include "agent_ui_layout.hh"
#include "agent_ui_model_card.hh"
#include "agent_ui_motion.hh"
#include "agent_ui_text.hh"
#include "agent_ui_theme.hh"

namespace blender {

namespace {

/* The chip's fills, by who answers (grey = credits, green = the user's key,
 * amber = local) and by state (red = the account's key is not on this
 * computer). Literal like the frames. */
constexpr float FILL_MIXIE[4] = {0x26 / 255.0f, 0x26 / 255.0f, 0x26 / 255.0f, 1.0f};
constexpr float FILL_KEY[4] = {0x0E / 255.0f, 0x27 / 255.0f, 0x14 / 255.0f, 1.0f};
constexpr float FILL_LOCAL[4] = {0x3A / 255.0f, 0x31 / 255.0f, 0x19 / 255.0f, 1.0f};
constexpr float FILL_NEEDED[4] = {0x4A / 255.0f, 0x1F / 255.0f, 0x1B / 255.0f, 1.0f};
constexpr float BADGE_MIXIE[4] = {0x3F / 255.0f, 0x3F / 255.0f, 0x3F / 255.0f, 1.0f};
constexpr float BADGE_KEY[4] = {0x2F / 255.0f, 0x4F / 255.0f, 0x36 / 255.0f, 1.0f};
constexpr float BADGE_LOCAL[4] = {0x4A / 255.0f, 0x3F / 255.0f, 0x1F / 255.0f, 1.0f};
constexpr float BADGE_NEEDED[4] = {0x6B / 255.0f, 0x2F / 255.0f, 0x2A / 255.0f, 1.0f};
constexpr float INK[4] = {1.0f, 1.0f, 1.0f, 1.0f};
constexpr float CHEVRON[4] = {0xAE / 255.0f, 0xAE / 255.0f, 0xAE / 255.0f, 1.0f};
/** A hovered shape lightens towards white by this much (pressed: twice). */
constexpr float HOVER_LIFT = 0.06f;
/** The name and chevron while a switch, pause or resume is being saved. */
constexpr float BUSY_ALPHA = 0.5f;

/** The weight the island's other text is drawn at: the widget style's. */
int widget_weight()
{
  const uiStyle *style = ui::style_get();
  return style ? style->widget.character_weight : AGENT_PROVIDER_WEIGHT_REGULAR;
}

/** Draw \a text left-aligned at (x, cy) like `ui::mixar_label_left`, at
 *  \a weight; the face goes back to the widget weight afterwards (Blender
 *  sets it per draw from the style, other island text assumes it). */
void label_weight(const char *text,
                  const float x,
                  const float cy,
                  const float size,
                  const float color[4],
                  const int weight)
{
  if (!text || !text[0]) {
    return;
  }
  const int font = BLF_default();
  BLF_character_weight(font, weight);
  ui::mixar_label_left(text, x, cy, size, color);
  BLF_character_weight(font, widget_weight());
}

void read_string(PointerRNA *ptr, const char *name, char *out, const int out_maxncpy)
{
  out[0] = '\0';
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  if (!prop || RNA_property_type(prop) != PROP_STRING) {
    return;
  }
  char fixed[256];
  int len = 0;
  char *value = RNA_property_string_get_alloc(ptr, prop, fixed, sizeof(fixed), &len);
  if (value) {
    BLI_strncpy_utf8(out, value, out_maxncpy);
    if (value != fixed) {
      MEM_delete(value);
    }
  }
}

void lift(const float base[4], const AgentIslandFeedback &fb, float r_color[4])
{
  const float t = std::min(1.0f, HOVER_LIFT * (fb.hover + fb.press));
  for (int i = 0; i < 3; i++) {
    r_color[i] = base[i] + (1.0f - base[i]) * t;
  }
  r_color[3] = base[3];
}

float radius_for(const rctf &rect, const float u)
{
  return std::min(AGENT_PROVIDER_RADIUS * u, BLI_rctf_size_y(&rect) * 0.5f);
}

void fills_for(const AgentIslandState &state, const float **r_fill, const float **r_badge)
{
  if (STREQ(state.model_chip_state, "KEY_NEEDED")) {
    *r_fill = FILL_NEEDED;
    *r_badge = BADGE_NEEDED;
  }
  else if (STREQ(state.model_source, "KEY")) {
    *r_fill = FILL_KEY;
    *r_badge = BADGE_KEY;
  }
  else if (STREQ(state.model_source, "LOCAL")) {
    *r_fill = FILL_LOCAL;
    *r_badge = BADGE_LOCAL;
  }
  else {
    *r_fill = FILL_MIXIE;
    *r_badge = BADGE_MIXIE;
  }
}

void draw_chip(ARegion *region,
               const AgentIslandLayout &layout,
               const AgentIslandState &state,
               const float size)
{
  const float u = layout.scale;
  const rctf &r = layout.chip_model;
  const AgentIslandFeedback feedback = agent_ui_motion_sample(
      region, AgentIslandControl::Model, r);
  const float *base_fill = nullptr;
  const float *badge_fill = nullptr;
  fills_for(state, &base_fill, &badge_fill);
  float fill[4];
  AgentIslandFeedback lit = feedback;
  if (agent_model_card_is_open()) {
    lit.press = std::max(lit.press, 1.0f); /* The card it opened is up. */
  }
  lift(base_fill, lit, fill);
  ui::mixar_fill_round(r, radius_for(r, u), fill);

  const float cy = BLI_rctf_cent_y(&r);
  const int strong = AGENT_PROVIDER_WEIGHT_STRONG;
  const bool busy = STREQ(state.model_chip_state, "BUSY");
  const float ink_alpha = busy ? BUSY_ALPHA : 1.0f;
  float x = r.xmin;

  /* The badge: a pill holding the source word, a size down. */
  if (layout.model_form != AgentModelChipForm::Label) {
    const float inset = AGENT_CHIP_BADGE_INSET * u;
    const float badge_size = size * AGENT_CHIP_BADGE_TEXT;
    const float word_w = agent_ui_provider_text_width(state.model_source_label, badge_size, strong);
    const float pill_w = AGENT_CHIP_BADGE_PAD * u + word_w + AGENT_CHIP_BADGE_PAD * u;
    const rctf pill{r.xmin + inset, std::min(r.xmax - inset, r.xmin + inset + pill_w),
                    r.ymin + inset, r.ymax - inset};
    ui::mixar_fill_round(pill, radius_for(pill, u), badge_fill);
    label_weight(state.model_source_label, pill.xmin + AGENT_CHIP_BADGE_PAD * u, cy, badge_size,
                 INK, strong);
    if (layout.model_form == AgentModelChipForm::Icon) {
      return;
    }
    x = pill.xmax + AGENT_CHIP_NAME_GAP * u;
  }
  else {
    x = r.xmin + AGENT_CHIP_NAME_PAD * u;
  }

  /* The name, fitted to what is left of the chip before the chevron. */
  const float chevron_w = AGENT_PROVIDER_CHEVRON_W * u;
  const float chevron_x = r.xmax - AGENT_CHIP_CHEVRON_PAD * u - chevron_w * 0.5f;
  const float text_end = chevron_x - chevron_w * 0.5f - AGENT_CHIP_CHEVRON_GAP * u * 0.5f;
  const int font = BLF_default();
  BLF_character_weight(font, strong);
  const std::string name = ui::mixar_fit_text(
      state.model_chip_name, std::max(0.0f, text_end - x), size);
  BLF_character_weight(font, widget_weight());
  const float ink[4] = {INK[0], INK[1], INK[2], ink_alpha};
  label_weight(name.c_str(), x, cy, size, ink, strong);
  const float col[4] = {CHEVRON[0], CHEVRON[1], CHEVRON[2], ink_alpha};
  agent_ui_chevron_fill_draw(chevron_x, cy, chevron_w, AGENT_PROVIDER_CHEVRON_H * u, col);
}

}  // namespace

float agent_ui_provider_text_width(const char *text, const float size, const int weight)
{
  const int font = BLF_default();
  BLF_character_weight(font, weight);
  const float width = ui::mixar_text_width(text, size);
  BLF_character_weight(font, widget_weight());
  return width;
}

void agent_ui_provider_gather(wmWindowManager *wm, AgentIslandState *r_state)
{
  r_state->model_available = false;
  BLI_strncpy(r_state->model_source, "MIXIE", sizeof(r_state->model_source));
  r_state->model_source_label[0] = '\0';
  r_state->model_chip_name[0] = '\0';
  BLI_strncpy(r_state->model_chip_state, "OK", sizeof(r_state->model_chip_state));
  if (!wm) {
    return;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  /* The picker mirrors are one registration batch (agent_model_props.py);
   * an older Python half, or a .blend opened before they registered, reads
   * as "no picker": no chip rather than a popup with nothing in it. */
  PropertyRNA *name = RNA_struct_find_property(&wm_ptr, "mixar_agent_chip_name");
  if (!name || RNA_property_type(name) != PROP_STRING) {
    return;
  }
  r_state->model_available = true;
  read_string(&wm_ptr, "mixar_agent_source", r_state->model_source, sizeof(r_state->model_source));
  read_string(&wm_ptr,
              "mixar_agent_source_label",
              r_state->model_source_label,
              sizeof(r_state->model_source_label));
  read_string(
      &wm_ptr, "mixar_agent_chip_name", r_state->model_chip_name, sizeof(r_state->model_chip_name));
  read_string(&wm_ptr,
              "mixar_agent_source_state",
              r_state->model_chip_state,
              sizeof(r_state->model_chip_state));
}

void agent_ui_draw_provider(ARegion *region,
                            const AgentIslandLayout *layout,
                            const AgentIslandState *state)
{
  /* The row is width-budgeted: the chip may have been dropped — an empty rect. */
  if (!state->model_available || BLI_rctf_size_x(&layout->chip_model) <= 0.0f) {
    return;
  }
  const float size = AGENT_CHIP_FONT * agent_ui_text_unit();
  draw_chip(region, *layout, *state, size);
}

void agent_bubble_provider_buttons(const bContext *C,
                                   ui::Block *block,
                                   const ARegion *region,
                                   const AgentIslandLayout &layout,
                                   const AgentIslandState &state)
{
  /* One native button over the whole chip; it opens the model card, which
   * is drawn by hand over the island window (agent_ui_model_card.cc). The
   * card anchors to the chip as last drawn here, so it follows the chip
   * wherever the island sits; a chip the row dropped closes it. */
  const bool shown = state.model_available && BLI_rctf_size_x(&layout.chip_model) > 0.0f;
  agent_model_card_anchor(
      CTX_wm_window(C), layout.chip_model, AGENT_CHIP_FONT * agent_ui_text_unit(), shown);
  if (!shown) {
    return;
  }
  const int x = int(layout.chip_model.xmin) - region->winrct.xmin;
  const int y = int(layout.chip_model.ymin) - region->winrct.ymin;
  const short w = short(BLI_rctf_size_x(&layout.chip_model));
  const short h = short(BLI_rctf_size_y(&layout.chip_model));
  ui::uiDefButO(block,
                ui::ButtonType::But,
                "MIXAR_OT_agent_model_card",
                wm::OpCallContext::InvokeDefault,
                "",
                x,
                y,
                w,
                h,
                TIP_("Who answers the agent and which model. Click to change"));
}

}  // namespace blender
