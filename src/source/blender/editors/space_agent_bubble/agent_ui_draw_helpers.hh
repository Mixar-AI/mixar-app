/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include "BLI_rect.h"
#include "ED_mixar_glass.hh"

namespace blender::agent_ui_draw_helpers {

void fill_round(const rctf *rect, const float radius, const float col[4]);

void outline_round(const rctf *rect, const float radius, const float col[4]);

void glass_fill_round(const rctf *rect,
                      const ui::eMixarGlassRole role,
                      const float radius,
                      const bool shadow = false,
                      const bool specular = false,
                      const bool tint = true,
                      const bool rim = true);

void fill_round_gradient(const rctf *rect,
                         const float radius,
                         const float c0[4],
                         const float c1[4],
                         const float a[2],
                         const float b[2]);

void draw_card_border_meter(const rctf *rect,
                            const float radius,
                            const float width,
                            const float lit[4],
                            const float spent[4],
                            const float remaining);

int island_font();

float text_width(const char *text, const float size);

void label_left(const char *text, const float x, const float cy, const float size,
                const float col[4]);

void label_centre(const char *text, const float cx, const float cy, const float size,
                  const float col[4]);

void label_right(const char *text, const float x, const float cy, const float size,
                 const float col[4]);

}  // namespace blender::agent_ui_draw_helpers
