/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * The sheet dialogs (AI Provider settings, Connect MCP) — the text kit,
 * the framed backdrop and the tags. The painters (text elements, close,
 * rows, chips, pills) are in `interface_mixar_sheet_controls.cc`, the
 * snippet, switch, status dot and foot glyphs in
 * `interface_mixar_sheet_blocks.cc`; the design is described in
 * `interface_mixar_sheet.hh`.
 *
 * Text is drawn straight through BLF rather than #fontstyle_draw: the sheet
 * sizes its text by Mixar's text roles and weights, which no #uiFontStyle can
 * name, and the artboard positions type by baseline and cap height, which the
 * style painter's ascender/descender centring cannot reproduce.
 */

#include <algorithm>
#include <cmath>
#include <cstring>
#include <string>

#include "BLI_math_color.h"
#include "BLI_rect.h"
#include "BLI_utildefines.h"

#include "BLF_api.hh"

#include "DNA_userdef_types.h"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "UI_interface_c.hh"
#include "UI_interface_layout.hh"
#include "UI_mixar.hh"
#include "UI_mixar_motion.hh"
#include "UI_resources.hh"

#include "interface_intern.hh"
#include "interface_mixar_card_paint.hh"
#include "interface_mixar_sheet.hh"
#include "mixar/cinema_label.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui {

namespace mixar_sheet {

float px(const float design_px)
{
  /* The Python layout sizes in UI units (`ui_units_x`, `scale_y`): one unit
   * is 40 design px and `U.widget_unit` region px. `widget_unit` is rounded
   * (29 px, not 30, at 150 %), so `0.5 * UI_SCALE_FAC` would drift from the
   * slots the layout hands the painter. */
  return design_px * float(UI_UNIT_X) / 40.0f;
}

/** The UI body size in region px: the widget font's points at the live
 * scale — the unit the Agent island and Mixar's text roles measure in. */
static float body_px()
{
  const uiStyle *style = style_get();
  return (style ? style->widget.points : UI_DEFAULT_TEXT_POINTS) * UI_SCALE_FAC;
}

static int widget_weight()
{
  const uiStyle *style = style_get();
  return style ? style->widget.character_weight : weight_regular;
}

int font(const float ratio, const int weight, const bool mono)
{
  const int id = mono ? blf_mono_font : BLF_default();
  BLF_size(id, body_px() * ratio);
  if (!mono) {
    BLF_character_weight(id, weight);
  }
  BLF_disable(id, BLF_CLIPPING);
  return id;
}

float text_width(const int font_id, const char *text)
{
  if (text == nullptr || text[0] == '\0') {
    return 0.0f;
  }
  return BLF_width(font_id, text, strlen(text));
}

float cap_height(const int font_id)
{
  rcti box;
  BLF_boundbox(font_id, "H", 1, &box);
  return float(std::max(box.ymax, 1));
}

/** Blender's widget text pass assumes the style's weight on the UI face:
 * every exit of a draw that called #font puts it back, empty text included
 * (an icon-only pill, a blank label). */
static void restore_weight(const int font_id)
{
  if (font_id == BLF_default()) {
    BLF_character_weight(font_id, widget_weight());
  }
}

void text_at(
    const int font_id, const float x, const float baseline, const char *text, const uchar col[4])
{
  if (text != nullptr && text[0] != '\0') {
    BLF_color4ubv(font_id, col);
    BLF_position(font_id, std::round(x), std::round(baseline), 0.0f);
    BLF_draw(font_id, text, strlen(text));
  }
  restore_weight(font_id);
}

std::string fit(const int font_id, const char *text, const float max_w)
{
  const size_t len = strlen(text);
  if (max_w <= 0.0f) {
    return "";
  }
  if (BLF_width(font_id, text, len) <= max_w) {
    return text;
  }
  const char *ellipsis = "\xe2\x80\xa6";
  const float ellipsis_w = BLF_width(font_id, ellipsis, 3);
  size_t keep = BLF_width_to_strlen(
      font_id, text, len, std::max(0.0f, max_w - ellipsis_w), nullptr);
  /* Back to a code-point boundary, then off any trailing space. */
  while (keep > 0 && (uchar(text[keep]) & 0xC0) == 0x80) {
    keep--;
  }
  while (keep > 0 && text[keep - 1] == ' ') {
    keep--;
  }
  return std::string(text, keep) + ellipsis;
}

void text_in(const int font_id,
             const rctf &rect,
             const char *text,
             const uchar col[4],
             const bool centre)
{
  if (text == nullptr || text[0] == '\0') {
    restore_weight(font_id);
    return;
  }
  const std::string shown = fit(font_id, text, BLI_rctf_size_x(&rect));
  const float w = BLF_width(font_id, shown.c_str(), shown.size());
  const float x = centre ? BLI_rctf_cent_x(&rect) - w * 0.5f : rect.xmin;
  const float baseline = BLI_rctf_cent_y(&rect) - cap_height(font_id) * 0.5f;
  text_at(font_id, x, baseline, shown.c_str(), col);
}

void stroke(const float x0,
            const float y0,
            const float x1,
            const float y1,
            const float width,
            const uchar col[4],
            const float alpha)
{
  /* The polyline shader anti-aliases at the real width; GPU_line_width is a
   * hairline on Metal. */
  float viewport[4];
  GPU_viewport_size_get_f(viewport);
  float c[4];
  rgba_uchar_to_float(c, col);
  c[3] *= alpha;
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_POLYLINE_UNIFORM_COLOR);
  immUniform2fv("viewportSize", &viewport[2]);
  immUniform1f("lineWidth", std::max(width, 1.0f));
  immUniform1i("lineSmooth", 1);
  immUniformColor4fv(c);
  immBegin(GPU_PRIM_LINES, 2);
  immVertex2f(pos, x0, y0);
  immVertex2f(pos, x1, y1);
  immEnd();
  immUnbindProgram();
}

rctf block_rect(const Button *but)
{
  /* Popup blocks project 1:1 onto their region, so block space is region
   * pixel space here (`block_to_region_fl` with the popup's ortho winmat). */
  return but->block->rect;
}

}  // namespace mixar_sheet

using namespace mixar_sheet;

/* -- Public API ---------------------------------------------------------- */

MixarCardElement UI_mixar_sheet_element_from_kind(const int kind)
{
  /* Values match `mixar_sheet_kind_items` in rna_ui_api.cc. */
  switch (kind) {
    case 1:
      return MixarCardElement::SheetTitle;
    case 2:
      return MixarCardElement::SheetClose;
    case 3:
      return MixarCardElement::SheetCaption;
    case 4:
      return MixarCardElement::SheetProviderRow;
    case 5:
      return MixarCardElement::SheetFooterRow;
    case 6:
      return MixarCardElement::SheetChip;
    case 7:
      return MixarCardElement::SheetPrompt;
    case 8:
      return MixarCardElement::SheetNote;
    case 9:
      return MixarCardElement::SheetBody;
    case 10:
      return MixarCardElement::SheetDangerText;
    case 11:
      return MixarCardElement::SheetPrimary;
    case 12:
      return MixarCardElement::SheetSecondary;
    case 13:
      return MixarCardElement::SheetDangerButton;
    case 14:
      return MixarCardElement::SheetInput;
    case 15:
      return MixarCardElement::SheetDropdown;
    case 16:
      return MixarCardElement::SheetSnippet;
    case 17:
      return MixarCardElement::SheetSwitch;
    case 18:
      return MixarCardElement::SheetStatusDot;
    default:
      return MixarCardElement::None;
  }
}

bool UI_mixar_sheet_element_is(const MixarCardElement element)
{
  return element >= MixarCardElement::SheetTitle && element <= MixarCardElement::SheetStatusDot;
}

void UI_layout_mixar_sheet_frame(Layout *layout, const float header_dp, const float sidebar_dp)
{
  Block *block = layout->block();
  block_flag_enable(block, BLOCK_MIXAR_SHEET);
  block->mixar_sheet_header = px(header_dp);
  block->mixar_sheet_sidebar = px(sidebar_dp);
}

void UI_layout_mixar_sheet_tag_last(Layout *layout,
                                    const MixarCardElement element,
                                    const bool lit,
                                    const float extra)
{
  Block *block = layout->block();
  if (block->buttons_ptrs.is_empty() || !UI_mixar_sheet_element_is(element)) {
    return;
  }
  Button *but = block->buttons_ptrs.last().get();
  if (element == MixarCardElement::SheetInput && but->type != ButtonType::Text) {
    /* A FILE_PATH / DIR_PATH property adds its browse button after the text
     * field: the field is the input, a step or two back. The browse button
     * becomes a docked secondary pill (icon only), like the Save beside it. */
    Button *browse = but;
    for (int i = int(block->buttons_ptrs.size()) - 2, steps = 0; i >= 0 && steps < 2;
         i--, steps++)
    {
      if (block->buttons_ptrs[i]->type == ButtonType::Text) {
        but = block->buttons_ptrs[i].get();
        break;
      }
    }
    if (but != browse) {
      MixarButtonStyle &pill = browse->mixar_style;
      pill.component = MixarComponent::LegacyCard;
      pill.card = MixarCardElement::SheetSecondary;
      pill.lit = false;
      pill.progress = 1.0f; /* Docked: the field's backdrop runs underneath. */
      if (!pill.explicit_theme) {
        pill.theme = MixarTheme::LegacyMixar;
      }
    }
  }
  MixarButtonStyle &style = but->mixar_style;
  if (ELEM(element, MixarCardElement::SheetInput, MixarCardElement::SheetDropdown)) {
    /* Native Text / Menu buttons: keep the stock input and text passes and
     * pick only the backdrop (see the ButtonType::Text / Menu cases in
     * `draw_button`). `mixar_style_button` refuses a type it cannot style. */
    const MixarComponent component = element == MixarCardElement::SheetInput ?
                                         MixarComponent::Input :
                                         MixarComponent::Dropdown;
    mixar_style_button(but, component, MixarVariant::Primary);
    if (style.component == component) {
      style.card = element;
      style.progress = extra;
    }
    return;
  }
  style.component = MixarComponent::LegacyCard;
  style.card = element;
  style.lit = lit;
  style.progress = extra;
  if (!style.explicit_theme) {
    style.theme = MixarTheme::LegacyMixar;
  }
}

float UI_mixar_sheet_text_width(const MixarCardElement element, const char *text)
{
  /* The same face, size and weight the painter draws \a element with. */
  float size = label_size;
  int weight = weight_medium;
  bool mono = false;
  switch (element) {
    case MixarCardElement::SheetTitle:
      size = title_size;
      weight = weight_strong;
      break;
    case MixarCardElement::SheetCaption:
      size = caption_size;
      mono = true;
      break;
    case MixarCardElement::SheetDangerText:
      size = note_size;
      weight = weight_medium;
      break;
    case MixarCardElement::SheetPrompt:
      size = prompt_size;
      break;
    case MixarCardElement::SheetNote:
      size = note_size;
      weight = weight_regular;
      break;
    case MixarCardElement::SheetBody:
    case MixarCardElement::SheetSwitch:
      /* A switch's label (Python adds the track and its gap). */
      size = body_size;
      weight = weight_regular;
      break;
    case MixarCardElement::SheetSnippet:
      size = snippet_size;
      weight = weight_regular;
      mono = true;
      break;
    case MixarCardElement::SheetPrimary:
    case MixarCardElement::SheetSecondary:
    case MixarCardElement::SheetDangerButton:
      weight = weight_strong;
      break;
    case MixarCardElement::SheetProviderRow:
    case MixarCardElement::SheetFooterRow:
      /* A row draws its name at the strong weight while lit, medium at rest:
       * sized for the wider face, picking a row never ellipsises its name. */
      weight = weight_strong;
      break;
    default:
      break;
  }
  /* In half design px (Python doubles it), on the layout's unit (see px). */
  const int font_id = font(size, weight, mono);
  const float w = text_width(font_id, text) * 20.0f / float(UI_UNIT_X);
  restore_weight(font_id);
  return w;
}

void UI_mixar_sheet_draw_back(const Block *block, const rcti *rect)
{
  rctf frame;
  BLI_rctf_rcti_copy(&frame, rect);
  const float rad = px(frame_radius);
  const float line = std::max(float(U.pixelsize), px(frame_line));
  float fill[4], border[4];
  rgba_uchar_to_float(fill, frame_fill);
  rgba_uchar_to_float(border, frame_border);

  GPU_blend(GPU_BLEND_ALPHA);

  /* The soft shadow every popup gets, under the card. */
  rctf shadow = frame;
  BLI_rctf_pad(&shadow, -float(U.pixelsize), -float(U.pixelsize));
  draw_roundbox_corner_set(CNR_ALL);
  draw_dropshadow(&shadow,
                  rad,
                  float(theme::get_menu_shadow_width()),
                  1.0f,
                  theme::theme_get()->tui.menu_shadow_fac);

  draw_roundbox_corner_set(CNR_ALL);
  draw_roundbox_4fv_ex(&frame, fill, fill, 0.0f, border, line, rad);

  /* Header divider across the card, sidebar divider down to the foot. */
  const float header = block->mixar_sheet_header;
  const float sidebar = block->mixar_sheet_sidebar;
  if (header > 0.0f) {
    const rctf rule = {
        frame.xmin + line, frame.xmax - line, frame.ymax - header - line * 0.5f, frame.ymax - header + line * 0.5f};
    draw_roundbox_4fv(&rule, true, 0.0f, border);
  }
  if (sidebar > 0.0f) {
    const rctf rule = {frame.xmin + sidebar - line * 0.5f,
                       frame.xmin + sidebar + line * 0.5f,
                       frame.ymin + line,
                       header > 0.0f ? frame.ymax - header : frame.ymax - line};
    draw_roundbox_4fv(&rule, true, 0.0f, border);
  }

  GPU_blend(GPU_BLEND_NONE);
}

bool UI_mixar_sheet_draw_element(Button *but, const rcti *rect, const MixarCardElement element)
{
  if (!UI_mixar_sheet_element_is(element)) {
    return false;
  }
  GPU_blend(GPU_BLEND_ALPHA);
  switch (element) {
    case MixarCardElement::SheetTitle:
      draw_title(but, rect);
      break;
    case MixarCardElement::SheetClose:
      draw_close(but, rect);
      break;
    case MixarCardElement::SheetCaption:
      draw_caption(but, rect);
      break;
    case MixarCardElement::SheetProviderRow:
      draw_provider_row(but, rect);
      break;
    case MixarCardElement::SheetFooterRow:
      draw_footer_row(but, rect);
      break;
    case MixarCardElement::SheetChip:
      draw_chip(but, rect);
      break;
    case MixarCardElement::SheetPrompt:
      draw_text(but, rect, prompt_size, text_body, weight_medium);
      break;
    case MixarCardElement::SheetNote:
      draw_text(but, rect, note_size, text_dim);
      break;
    case MixarCardElement::SheetBody:
      draw_text(but, rect, body_size, text_body);
      break;
    case MixarCardElement::SheetDangerText:
      draw_text(but, rect, note_size, text_danger, weight_medium);
      break;
    case MixarCardElement::SheetPrimary:
    case MixarCardElement::SheetSecondary:
    case MixarCardElement::SheetDangerButton:
      draw_pill(but, rect, element);
      break;
    case MixarCardElement::SheetInput:
      UI_mixar_sheet_input_draw(but, rect);
      break;
    case MixarCardElement::SheetDropdown:
      UI_mixar_sheet_dropdown_draw(but, rect);
      break;
    case MixarCardElement::SheetSnippet:
      draw_snippet(but, rect);
      break;
    case MixarCardElement::SheetSwitch:
      draw_switch(but, rect);
      break;
    case MixarCardElement::SheetStatusDot:
      draw_status_dot(but, rect);
      break;
    default:
      break;
  }
  GPU_blend(GPU_BLEND_NONE);
  return true;
}

}  // namespace blender::ui
