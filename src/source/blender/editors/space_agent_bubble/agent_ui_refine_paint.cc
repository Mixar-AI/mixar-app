/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Refine / Revert left of Send: the moodboard node's prompt pair, painted in
 * the island's chip idiom. The native buttons over these rects are placed by
 * #agent_bubble_send_button and run `mixie.refine_prompt` /
 * `mixie.revert_prompt` with `chat=True` (moodboard/core/prompt_refine_chat.py).
 */

#include "BLI_rect.h"

#include "UI_mixar.hh"

#include "agent_ui_draw.hh"
#include "agent_ui_icons.hh"
#include "agent_ui_layout.hh"
#include "agent_ui_motion.hh"
#include "agent_ui_theme.hh"

namespace blender {

namespace {
void draw_square(ARegion *region,
                 const AgentIslandControl control,
                 const rctf &rect,
                 const AgentIcon glyph,
                 const bool enabled,
                 const float scale)
{
  MIXAR_THEME_LOAD(chip, Chip);
  MIXAR_THEME_LOAD(text, Text);
  MIXAR_THEME_LOAD(text_dim, TextSecondary);
  float fill[4];
  agent_ui_motion_color(chip, chip, agent_ui_motion_sample(region, control, rect), fill);
  ui::mixar_fill_round(rect, AGENT_CHIP_RADIUS * scale, fill);

  const float edge = AGENT_CHIP_ICON * scale;
  const float cx = BLI_rctf_cent_x(&rect);
  const float cy = BLI_rctf_cent_y(&rect);
  const rctf icon{cx - edge * 0.5f, cx + edge * 0.5f, cy - edge * 0.5f, cy + edge * 0.5f};
  /* Dimmed rather than hidden: the button keeps its place so Send never
   * shifts under the pointer while a draft is typed. */
  agent_ui_icon_draw(glyph, &icon, enabled ? text : text_dim, fill);
}
}  // namespace

void agent_ui_draw_refine_controls(ARegion *region,
                                   const AgentIslandLayout *layout,
                                   const AgentIslandState *state)
{
  if (BLI_rctf_size_x(&layout->btn_refine) <= 0.0f) {
    return;
  }
  const bool can_refine = !state->prompt_empty && !state->prompt_refining;
  draw_square(region,
              AgentIslandControl::Refine,
              layout->btn_refine,
              AGENT_ICON_SPARKLE,
              can_refine,
              layout->scale);
  if (BLI_rctf_size_x(&layout->btn_revert) > 0.0f) {
    draw_square(region,
                AgentIslandControl::Revert,
                layout->btn_revert,
                AGENT_ICON_RESTORE,
                !state->prompt_refining,
                layout->scale);
  }
}

}  // namespace blender
