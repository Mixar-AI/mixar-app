/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * The engine chip. See agent_ui_engine.hh.
 */

#include "agent_ui_engine.hh"

#include <algorithm>
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
#include "agent_ui_provider.hh"
#include "agent_ui_text.hh"
#include "agent_ui_theme.hh"

namespace blender {

namespace {

/* The model chip's grey, so the two read as one family; the dot carries the
 * state. Literal like the frames. */
constexpr float FILL[4] = {0x26 / 255.0f, 0x26 / 255.0f, 0x26 / 255.0f, 1.0f};
constexpr float DOT_CONNECTED[4] = {0x3D / 255.0f, 0xC2 / 255.0f, 0x5C / 255.0f, 1.0f};
constexpr float DOT_OFF[4] = {0x6B / 255.0f, 0x6B / 255.0f, 0x6B / 255.0f, 1.0f};
constexpr float DOT_BUSY[4] = {0xE0 / 255.0f, 0xA8 / 255.0f, 0x2E / 255.0f, 1.0f};
constexpr float DOT_ERROR[4] = {0xE0 / 255.0f, 0x55 / 255.0f, 0x4A / 255.0f, 1.0f};
constexpr float INK[4] = {1.0f, 1.0f, 1.0f, 1.0f};
constexpr float INK_OFF[4] = {0xC8 / 255.0f, 0xC8 / 255.0f, 0xC8 / 255.0f, 1.0f};
constexpr float CHEVRON[4] = {0xAE / 255.0f, 0xAE / 255.0f, 0xAE / 255.0f, 1.0f};
constexpr float HOVER_LIFT = 0.06f;

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

const float *dot_for(const char *state)
{
  if (STREQ(state, "CONNECTED")) {
    return DOT_CONNECTED;
  }
  if (STREQ(state, "BUSY")) {
    return DOT_BUSY;
  }
  if (STREQ(state, "ERROR")) {
    return DOT_ERROR;
  }
  return DOT_OFF;
}

int widget_weight()
{
  const uiStyle *style = ui::style_get();
  return style ? style->widget.character_weight : AGENT_PROVIDER_WEIGHT_REGULAR;
}

void draw_chip(ARegion *region,
               const AgentIslandLayout &layout,
               const AgentIslandState &state,
               const float size)
{
  const float u = layout.scale;
  const rctf &r = layout.chip_engine;
  AgentIslandFeedback fb = agent_ui_motion_sample(region, AgentIslandControl::Engine, r);
  if (agent_engine_card_is_open()) {
    fb.press = std::max(fb.press, 1.0f); /* The card it opened is up. */
  }
  float fill[4];
  const float t = std::min(1.0f, HOVER_LIFT * (fb.hover + fb.press));
  for (int i = 0; i < 3; i++) {
    fill[i] = FILL[i] + (1.0f - FILL[i]) * t;
  }
  fill[3] = 1.0f;
  const float radius = std::min(AGENT_PROVIDER_RADIUS * u, BLI_rctf_size_y(&r) * 0.5f);
  ui::mixar_fill_round(r, radius, fill);

  /* The status dot: a circle is a round rect as wide as it is tall. */
  const float cy = BLI_rctf_cent_y(&r);
  const float d = AGENT_ENGINE_DOT * u;
  const float dot_x = layout.engine_icon_only ? BLI_rctf_cent_x(&r) - d * 0.5f :
                                                r.xmin + AGENT_ENGINE_DOT_PAD * u;
  const rctf dot{dot_x, dot_x + d, cy - d * 0.5f, cy + d * 0.5f};
  ui::mixar_fill_round(dot, d * 0.5f, dot_for(state.engine_state));
  if (layout.engine_icon_only) {
    return;
  }

  /* The name, fitted before the chevron. */
  const float x = dot.xmax + AGENT_ENGINE_DOT_GAP * u;
  const float chevron_w = AGENT_PROVIDER_CHEVRON_W * u;
  const float chevron_x = r.xmax - AGENT_CHIP_CHEVRON_PAD * u - chevron_w * 0.5f;
  const float text_end = chevron_x - chevron_w * 0.5f - AGENT_CHIP_CHEVRON_GAP * u * 0.5f;
  const int font = BLF_default();
  const int strong = AGENT_PROVIDER_WEIGHT_STRONG;
  BLF_character_weight(font, strong);
  const std::string name = ui::mixar_fit_text(state.engine_chip_name, std::max(0.0f, text_end - x),
                                              size);
  ui::mixar_label_left(name.c_str(), x, cy, size,
                       STREQ(state.engine_state, "CONNECTED") ? INK : INK_OFF);
  BLF_character_weight(font, widget_weight());
  agent_ui_chevron_fill_draw(chevron_x, cy, chevron_w, AGENT_PROVIDER_CHEVRON_H * u, CHEVRON);
}

}  // namespace

void agent_ui_engine_gather(wmWindowManager *wm, AgentIslandState *r_state)
{
  r_state->engine_available = false;
  r_state->engine_chip_name[0] = '\0';
  BLI_strncpy(r_state->engine_state, "OFF", sizeof(r_state->engine_state));
  if (!wm) {
    return;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  /* An older Python half (no mirror) reads as no chip, not an empty one. */
  PropertyRNA *name = RNA_struct_find_property(&wm_ptr, "mixar_engine_chip_name");
  if (!name || RNA_property_type(name) != PROP_STRING) {
    return;
  }
  read_string(&wm_ptr, "mixar_engine_chip_name", r_state->engine_chip_name,
              sizeof(r_state->engine_chip_name));
  read_string(&wm_ptr, "mixar_engine_state", r_state->engine_state, sizeof(r_state->engine_state));
  r_state->engine_available = r_state->engine_chip_name[0] != '\0';
}

void agent_ui_draw_engine(ARegion *region, const AgentIslandLayout *layout, const AgentIslandState *state)
{
  if (!state->engine_available || BLI_rctf_size_x(&layout->chip_engine) <= 0.0f) {
    return;
  }
  draw_chip(region, *layout, *state, AGENT_CHIP_FONT * agent_ui_text_unit());
}

void agent_bubble_engine_buttons(const bContext *C,
                                 ui::Block *block,
                                 const ARegion *region,
                                 const AgentIslandLayout &layout,
                                 const AgentIslandState &state)
{
  const bool shown = state.engine_available && BLI_rctf_size_x(&layout.chip_engine) > 0.0f;
  agent_engine_card_anchor(
      CTX_wm_window(C), layout.chip_engine, AGENT_CHIP_FONT * agent_ui_text_unit(), shown);
  if (!shown) {
    return;
  }
  const int x = int(layout.chip_engine.xmin) - region->winrct.xmin;
  const int y = int(layout.chip_engine.ymin) - region->winrct.ymin;
  const short w = short(BLI_rctf_size_x(&layout.chip_engine));
  const short h = short(BLI_rctf_size_y(&layout.chip_engine));
  ui::uiDefButO(block,
                ui::ButtonType::But,
                "MIXAR_OT_agent_engine_card",
                wm::OpCallContext::InvokeDefault,
                "",
                x,
                y,
                w,
                h,
                TIP_("The game engine the agent builds in. Click to switch or connect one"));
}

}  // namespace blender
