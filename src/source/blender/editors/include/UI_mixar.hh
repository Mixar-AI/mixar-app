/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include "BLI_rect.h"
#include "UI_mixar_density.hh"
#include "UI_mixar_text.hh"
#include "UI_mixar_chrome.hh"
#include "UI_mixar_types.hh"
#include <cstdint>
#include <string>
struct bContext;

namespace blender {
struct ARegion;
struct uiWidgetColors;
}

namespace blender::ui {
struct Button;
struct Layout;
void mixar_style_last(Layout *layout, MixarComponent component, MixarVariant variant);
int64_t mixar_button_count(const Layout *layout);
void mixar_style_new_buttons(Layout *layout,
                             int64_t first,
                             MixarComponent component,
                             bool multiline = false);
void mixar_style_button(Button *button,
                        MixarComponent component,
                        MixarVariant variant = MixarVariant::Primary,
                        float unit = 0.0f);
void mixar_style_card(Button *button, MixarCardElement element, float legacy_payload);
const char *mixar_component_name(MixarComponent component);
const char *mixar_theme_name(MixarTheme theme);
const char *mixar_variant_name(MixarVariant variant);
/** Draws the component backdrop; true means the native text pass is still
 * required. */
bool mixar_component_draw(Button &button, uiWidgetColors &colors, const rcti &rect);
void mixar_fill_round(const rctf &rect, float radius, const float color[4]);
float mixar_text_width(const char *text, float size);
void mixar_label_left(const char *text, float x, float cy, float size, const float color[4]);
std::string mixar_fit_text(const char *text, float max_width, float size);
/** Typed text overloads keep measure, fit and paint on one resolved style. */
inline float mixar_text_width(const char *text, const MixarTextStyle style)
{
  return mixar_text_width(text, style.size);
}
inline std::string mixar_fit_text(const char *text, float max_width, const MixarTextStyle style)
{
  return mixar_fit_text(text, max_width, style.size);
}
inline void mixar_label_left(
    const char *text, float x, float cy, const MixarTextStyle style, const float color[4])
{
  mixar_label_left(text, x, cy, style.size, color);
}
inline void mixar_label_right(
    const char *text, float x, float cy, const MixarTextStyle style, const float color[4])
{
  mixar_label_left(text, x - mixar_text_width(text, style), cy, style, color);
}
inline void mixar_label_center(
    const char *text, float x, float cy, const MixarTextStyle style, const float color[4])
{
  mixar_label_left(text, x - mixar_text_width(text, style) * 0.5f, cy, style, color);
}
void mixar_button_tooltip_owned(Button *button, const char *text);
void mixar_button_lit_set(Button *button, bool lit);
/** True when the context workspace is Mixar's dedicated Zen Mode tab. */
bool mixar_workspace_is_zen(const bContext *C);
/**
 * Paint the Zen topbar / View3D header as the family's ISLAND pane instead
 * of the theme header slab. Returns true when the caller must skip
 * `ED_region_clear` — dest-over cannot lower an opaque theme clear.
 */
bool mixar_zen_header_clear(const bContext *C, const ARegion *region);
}  // namespace blender::ui
