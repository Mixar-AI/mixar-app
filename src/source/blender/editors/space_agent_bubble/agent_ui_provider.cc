/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * The Mixie | Custom AI toggle and the key chip. See agent_ui_provider.hh.
 */

#include "agent_ui_provider.hh"

#include <algorithm>
#include <cmath>
#include <string>

#include "MEM_guardedalloc.h"

#include "BLI_rect.h"
#include "BLI_string_utf8.h"

#include "BLF_api.hh"

#include "BLT_translation.hh"

#include "BKE_screen.hh"

#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_interface_layout.hh"
#include "UI_mixar.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "agent_ui_chip_fit.hh"
#include "agent_ui_draw.hh"
#include "agent_ui_icons.hh"
#include "agent_ui_layout.hh"
#include "agent_ui_motion.hh"
#include "agent_ui_text.hh"
#include "agent_ui_theme.hh"

namespace blender {

namespace {

/* The designer's palette for both controls, literal like the frames. */
constexpr float TRACK[4] = {0x26 / 255.0f, 0x26 / 255.0f, 0x26 / 255.0f, 1.0f};
constexpr float THUMB[4] = {0x1D / 255.0f, 0x5A / 255.0f, 0x2A / 255.0f, 1.0f};
constexpr float INK[4] = {1.0f, 1.0f, 1.0f, 1.0f};
constexpr float INK_DIM[4] = {0x99 / 255.0f, 0x99 / 255.0f, 0x99 / 255.0f, 1.0f};
constexpr float CHEVRON[4] = {0xAE / 255.0f, 0xAE / 255.0f, 0xAE / 255.0f, 1.0f};
constexpr float CHIP[4] = {0x0E / 255.0f, 0x27 / 255.0f, 0x14 / 255.0f, 1.0f};
constexpr float PILL[4] = {0x2F / 255.0f, 0x4F / 255.0f, 0x36 / 255.0f, 1.0f};
/** A hovered shape lightens towards white by this much (pressed: twice). */
constexpr float HOVER_LIFT = 0.06f;
/** The model word and chevron while a switch is being saved. */
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

bool read_bool(PointerRNA *ptr, const char *name)
{
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  return (prop && RNA_property_type(prop) == PROP_BOOLEAN) ? RNA_property_boolean_get(ptr, prop) :
                                                             false;
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

/** The key chip's model pill, in window space. */
rctf key_pill(const AgentIslandLayout &layout, const AgentIslandState &state, const float size)
{
  const float u = layout.scale;
  const float inset = AGENT_KEY_PILL_INSET * u;
  rctf pill = layout.chip_key;
  BLI_rctf_pad(&pill, -inset, -inset);
  if (!layout.key_compact) {
    pill.xmin = layout.chip_key.xmin + AGENT_KEY_CHIP_PAD * u +
                ui::mixar_text_width(state.model_key_label, size) + AGENT_KEY_CHIP_TEXT_GAP * u;
  }
  pill.xmin = std::min(pill.xmin, pill.xmax);
  return pill;
}

void draw_toggle(ARegion *region,
                 const AgentIslandLayout &layout,
                 const AgentIslandState &state,
                 const float size)
{
  const float u = layout.scale;
  const rctf &r = layout.chip_model;
  const AgentIslandFeedback feedback = agent_ui_motion_sample(
      region, AgentIslandControl::Model, r, state.model_byok_active);
  float track[4];
  lift(TRACK, feedback, track);
  ui::mixar_fill_round(r, radius_for(r, u), track);

  const float cy = BLI_rctf_cent_y(&r);
  if (layout.model_form == AgentModelChipForm::Icon) {
    const float edge = AGENT_CHIP_ICON * u;
    const float cx = BLI_rctf_cent_x(&r);
    const rctf glyph{cx - edge * 0.5f, cx + edge * 0.5f, cy - edge * 0.5f, cy + edge * 0.5f};
    agent_ui_icon_draw(AGENT_ICON_STAR, &glyph, INK, track);
    return;
  }

  /* The thumb slides between the two segments on the shared Zen timing
   * (`feedback.selected` follows the key being in use). */
  const float inset = AGENT_TOGGLE_THUMB_INSET * u;
  const float split = layout.model_split_x;
  const rctf mixie{r.xmin + inset, split, r.ymin + inset, r.ymax - inset};
  const rctf key{split, r.xmax - inset, r.ymin + inset, r.ymax - inset};
  const float t = feedback.selected;
  const rctf thumb{mixie.xmin + (key.xmin - mixie.xmin) * t,
                   mixie.xmax + (key.xmax - mixie.xmax) * t,
                   mixie.ymin,
                   mixie.ymax};
  ui::mixar_fill_round(thumb, radius_for(thumb, u), THUMB);

  /* Literal msgids so the i18n extractor sees them; they must match
   * AGENT_MODEL_TOGGLE_MIXIE / _KEY, which size the segments. */
  float mixie_ink[4], key_ink[4];
  agent_ui_motion_color(INK, INK_DIM, {0.0f, 0.0f, t}, mixie_ink);
  agent_ui_motion_color(INK_DIM, INK, {0.0f, 0.0f, t}, key_ink);
  const float pad = AGENT_TOGGLE_SEG_PAD * u;
  const char *mixie_word = IFACE_("Mixie");
  const int strong = AGENT_PROVIDER_WEIGHT_STRONG;
  label_weight(mixie_word, mixie.xmin + pad, cy, size, mixie_ink, strong);
  if (!state.model_byok_active) {
    /* Mixie opens the hosted model menu only while it is the one in use. */
    const float x = mixie.xmin + pad + agent_ui_provider_text_width(mixie_word, size, strong) +
                    AGENT_TOGGLE_CHEVRON_GAP * u;
    const float w = AGENT_PROVIDER_CHEVRON_W * u;
    agent_ui_chevron_fill_draw(x + w * 0.5f, cy, w, AGENT_PROVIDER_CHEVRON_H * u, CHEVRON);
  }
  label_weight(IFACE_("Custom AI"), key.xmin + pad, cy, size, key_ink, strong);
}

void draw_key_chip(ARegion *region,
                   const AgentIslandLayout &layout,
                   const AgentIslandState &state,
                   const float size)
{
  const float u = layout.scale;
  const rctf &chip = layout.chip_key;
  const rctf pill = key_pill(layout, state, size);
  const AgentIslandFeedback chip_fb = agent_ui_motion_sample(
      region, AgentIslandControl::KeyChip, chip);
  const AgentIslandFeedback pill_fb = agent_ui_motion_sample(
      region, AgentIslandControl::KeyModel, pill);
  float fill[4];
  lift(CHIP, chip_fb, fill);
  ui::mixar_fill_round(chip, radius_for(chip, u), fill);
  const float cy = BLI_rctf_cent_y(&chip);
  if (!layout.key_compact) {
    ui::mixar_label_left(
        state.model_key_label, chip.xmin + AGENT_KEY_CHIP_PAD * u, cy, size, INK_DIM);
  }

  lift(PILL, pill_fb, fill);
  ui::mixar_fill_round(pill, radius_for(pill, u), fill);
  const float model_size = size * AGENT_KEY_MODEL_TEXT;
  const float chevron_w = AGENT_PROVIDER_CHEVRON_W * u;
  const float text_x = pill.xmin + AGENT_KEY_PILL_PAD * u;
  const float text_end = state.model_key_menu ?
                             pill.xmax - (AGENT_KEY_PILL_CHEVRON_PAD * u + chevron_w +
                                          AGENT_KEY_PILL_CHEVRON_GAP * u * 0.5f) :
                             pill.xmax - AGENT_KEY_PILL_PAD * u;
  const int font = BLF_default();
  BLF_character_weight(font, AGENT_PROVIDER_WEIGHT_STRONG);
  const std::string model = ui::mixar_fit_text(
      state.model_key_model, std::max(0.0f, text_end - text_x), model_size);
  BLF_character_weight(font, widget_weight());
  float ink[4] = {INK[0], INK[1], INK[2], state.model_key_busy ? BUSY_ALPHA : 1.0f};
  label_weight(model.c_str(), text_x, cy, model_size, ink, AGENT_PROVIDER_WEIGHT_STRONG);
  if (state.model_key_menu) {
    float col[4] = {CHEVRON[0], CHEVRON[1], CHEVRON[2], state.model_key_busy ? BUSY_ALPHA : 1.0f};
    const float x = pill.xmax - AGENT_KEY_PILL_CHEVRON_PAD * u - chevron_w * 0.5f;
    agent_ui_chevron_fill_draw(x, cy, chevron_w, AGENT_PROVIDER_CHEVRON_H * u, col);
  }
}

void to_region(const ARegion *region, const rctf &src, int *r_x, int *r_y, short *r_w, short *r_h)
{
  *r_x = int(src.xmin) - region->winrct.xmin;
  *r_y = int(src.ymin) - region->winrct.ymin;
  *r_w = short(BLI_rctf_size_x(&src));
  *r_h = short(BLI_rctf_size_y(&src));
}

void menu_but(ui::Block *block,
              const ARegion *region,
              const rctf &rect,
              const char *menu,
              const char *tip)
{
  int x, y;
  short w, h;
  to_region(region, rect, &x, &y, &w, &h);
  uiDefMenuBut(
      block,
      [](bContext *C, ui::Layout *menu_layout, void *arg) {
        MenuType *mt = WM_menutype_find(static_cast<const char *>(arg), false);
        if (mt != nullptr) {
          ui::menutype_draw(C, mt, menu_layout);
        }
      },
      const_cast<char *>(menu),
      "",
      x,
      y,
      w,
      h,
      tip);
}

void op_but(ui::Block *block,
            const ARegion *region,
            const rctf &rect,
            const char *op,
            const char *tip)
{
  int x, y;
  short w, h;
  to_region(region, rect, &x, &y, &w, &h);
  uiDefButO(
      block, ui::ButtonType::But, op, blender::wm::OpCallContext::InvokeDefault, "", x, y, w, h, tip);
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
  r_state->model_byok_active = false;
  r_state->model_label[0] = '\0';
  r_state->model_key_label[0] = '\0';
  r_state->model_key_model[0] = '\0';
  r_state->model_key_menu = false;
  r_state->model_key_busy = false;
  if (!wm) {
    return;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *label = RNA_struct_find_property(&wm_ptr, "mixar_agent_model_label");
  if (!label || RNA_property_type(label) != PROP_STRING) {
    return;
  }
  r_state->model_available = true;
  read_string(&wm_ptr, "mixar_agent_model_label", r_state->model_label, sizeof(r_state->model_label));
  r_state->model_byok_active = read_bool(&wm_ptr, "mixar_agent_model_byok_active");
  if (!r_state->model_byok_active) {
    return;
  }
  read_string(
      &wm_ptr, "mixar_agent_key_label", r_state->model_key_label, sizeof(r_state->model_key_label));
  read_string(
      &wm_ptr, "mixar_agent_key_model", r_state->model_key_model, sizeof(r_state->model_key_model));
  r_state->model_key_menu = read_bool(&wm_ptr, "mixar_agent_key_menu");
  r_state->model_key_busy = read_bool(&wm_ptr, "mixar_agent_key_busy");
}

void agent_ui_draw_provider(ARegion *region,
                            const AgentIslandLayout *layout,
                            const AgentIslandState *state)
{
  /* The row is width-budgeted: the toggle may have been stepped down to a
   * lone icon (no chip), or dropped entirely — an empty rect. */
  if (!state->model_available || BLI_rctf_size_x(&layout->chip_model) <= 0.0f) {
    return;
  }
  const float size = AGENT_CHIP_FONT * agent_ui_text_unit();
  draw_toggle(region, *layout, *state, size);
  if (BLI_rctf_size_x(&layout->chip_key) > 0.0f) {
    draw_key_chip(region, *layout, *state, size);
  }
}

void agent_bubble_provider_buttons(ui::Block *block,
                                   const ARegion *region,
                                   const AgentIslandLayout &layout,
                                   const AgentIslandState &state)
{
  /* Two native buttons over the painted toggle, split at the seam the layout
   * shares with the painter. Mixie while it is in use pops the hosted model
   * menu (a pulldown anchored to this half). Mixie while a key is in use
   * (`mixar_byok.use_mixie`, its own operator: block rebuilds match the
   * active button to its predecessor by operator type, so two adjacent
   * `open_dialog` buttons with different properties could trade them) opens
   * AI Provider settings on its remove confirmation, because a key is active
   * exactly while it is stored. Custom AI always opens AI Provider settings.
   * The fitted-down icon form keeps the hosted menu. */
  if (!state.model_available || BLI_rctf_size_x(&layout.chip_model) <= 0.0f) {
    return;
  }
  const bool toggle = layout.model_form != AgentModelChipForm::Icon;
  rctf mixie = layout.chip_model;
  rctf key = layout.chip_model;
  if (toggle) {
    mixie.xmax = layout.model_split_x;
    key.xmin = layout.model_split_x;
  }
  if (state.model_byok_active && toggle) {
    op_but(block,
           region,
           mixie,
           "mixar_byok.use_mixie",
           TIP_("Switch back to Mixie, Mixar's hosted models. This removes your saved API key"));
  }
  else {
    menu_but(block,
             region,
             mixie,
             "MIXIE_CHAT_MT_agent_model",
             state.model_byok_active ?
                 TIP_("Your own API key is in use, and it decides the model") :
                 TIP_("Mixie is answering. Click to choose which Mixie model the agent runs on"));
  }
  if (toggle) {
    op_but(block,
           region,
           key,
           "mixar_byok.open_dialog",
           state.model_byok_active ?
               TIP_("Your own API key is in use, so Mixar credits are not charged. "
                    "Click to change it") :
               TIP_("Use your own API key: pick a provider and model in AI Provider "
                    "settings. Mixar credits are not charged while it is in use"));
  }

  /* The key chip: its model pill switches the model in place (no dialog);
   * the provider word opens AI Provider settings. OpenRouter and Local have
   * no fixed model list, so there the whole chip opens the settings. */
  if (BLI_rctf_size_x(&layout.chip_key) <= 0.0f) {
    return;
  }
  const float size = AGENT_CHIP_FONT * agent_ui_text_unit();
  if (!state.model_key_menu) {
    op_but(block,
           region,
           layout.chip_key,
           "mixar_byok.open_dialog",
           TIP_("The model your API key runs the agent on. Click to change it in AI Provider "
                "settings"));
    return;
  }
  const rctf pill = key_pill(layout, state, size);
  if (!layout.key_compact) {
    rctf provider = layout.chip_key;
    provider.xmax = pill.xmin;
    op_but(block,
           region,
           provider,
           "mixar_byok.open_dialog",
           TIP_("Your own API key is in use. Click to change the provider or key"));
  }
  menu_but(block,
           region,
           pill,
           "MIXAR_BYOK_MT_key_model",
           TIP_("Choose which model your API key runs the agent on"));
}

}  // namespace blender
