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
namespace blender {
struct bContext;
struct ARegion;
struct ScrArea;
struct uiWidgetColors;
}

namespace blender::ui {
struct Button;
struct Block;
struct Layout;
/** Clip an embedded surface without resizing or moving its native widgets. */
void mixar_block_clip_set(Block *block, const rctf &rect);
/** Intersect a region-pixel rectangle with the same clip used by paint/input. */
bool mixar_block_clip_pixelrect(const ARegion *region, const Block *block, rcti *rect);
/** Intersect the current GPU scissor with the block viewport for drawing. */
void mixar_block_clip_apply(const ARegion *region, const Block *block);
void mixar_style_last(Layout *layout, MixarComponent component, MixarVariant variant,
                      bool all_items = false, bool selected = false);
int64_t mixar_button_count(const Layout *layout);
void mixar_style_new_buttons(Layout *layout,
                             int64_t first,
                             MixarComponent component,
                             bool multiline = false);
void mixar_style_button(Button *button,
                        MixarComponent component,
                        MixarVariant variant = MixarVariant::Primary,
                        float unit = 0.0f,
                        float text_unit = 0.0f);
void mixar_style_card(Button *button, MixarCardElement element, float legacy_payload);
const char *mixar_component_name(MixarComponent component);
const char *mixar_theme_name(MixarTheme theme);
const char *mixar_variant_name(MixarVariant variant);
/** Draws the component backdrop; true means the native text pass is still
 * required. */
bool mixar_component_draw(Button &button, uiWidgetColors &colors, const rcti &rect);
bool mixar_toolbar_draw(Button &button, uiWidgetColors &colors, const rcti &rect);
/** Symmetric content inset for tall Zen inputs; native caret/wrap use this rect. */
bool mixar_multiline_input_rect(const Button &button, const rcti &bounds, rcti &text_rect);
/** Premultiplied rounded fill that replaces dest alpha for opaque colours.
 * Widget dest-over leaves frost-window dest A at the 0.20 wash on WGL. */
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
 * Zen Mode's View3D headers use the established overlapping region layout.
 * Its scene toolbar reserves the top edge. No other workspace qualifies —
 * Texturing keeps Blender's full opaque viewport header.
 */
bool mixar_workspace_floats_viewport_chrome(const bContext *C);
bool mixar_area_floats_viewport_chrome(const ScrArea *area);
/**
 * Paint the Zen topbar as the family's ISLAND pane instead of the theme
 * header slab. View3D headers use their own toolbar bed. Returns true when
 * the caller must skip
 * `ED_region_clear` — dest-over cannot lower an opaque theme clear.
 */
bool mixar_zen_header_clear(const bContext *C, const ARegion *region);
/** Zen scene-toolbar bed / transparent empty tool-header clear. */
bool mixar_zen_floating_header_clear(const bContext *C, const ARegion *region);
}  // namespace blender::ui
