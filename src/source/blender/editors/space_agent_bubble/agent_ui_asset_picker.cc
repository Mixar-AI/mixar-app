/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Asset picker — the frame and the tile grid. The detail column is
 * `agent_ui_asset_picker_detail.cc`; the geometry is
 * `agent_ui_asset_picker_layout.hh` (the Library's own resolver, re-used).
 *
 * Every painter below is the Library pane's: `pane_wash_paint`, the hairline
 * divider, `GEN_COL_TILE` plates with the design's corner radius, the
 * two-line caption (kind + score on the first line where the Library has
 * kind + age, the name on the second), the accent selection ring drawn last
 * under the grid clip, and the dim mesh glyph while a preview is still
 * rendering. Thumbnails are the chat's own asset-choice previews
 * (`asset_choice_previews.py` renders them into `bpy.data.images`), so the
 * picker needs no preview pipeline of its own.
 */

#include "agent_ui_text.hh"
#include "agent_ui_generations_clip.hh"

#include <algorithm>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <string>

#include "BLI_listbase.h"
#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"
#include "BKE_image.hh"
#include "BKE_main.hh"

#include "IMB_imbuf_types.hh"

#include "DNA_ID.h"
#include "DNA_image_types.h"
#include "DNA_screen_types.h"
#include "DNA_windowmanager_types.h"

#include "GPU_state.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
/* The tile's drag image (`Button::imb`) has no public setter for a name
 * drag; the moodboard's template drag reaches into the button the same way. */
#include "../interface/interface_intern.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "ED_mixie_chat_asset_picker.hh"

#include "agent_ui_asset_picker.hh"
#include "agent_ui_asset_picker_intern.hh"
#include "agent_ui_generations_intern.hh"
#include "agent_ui_icons.hh"
#include "agent_ui_pane_kit.hh"
#include "agent_ui_theme.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Shared helpers (agent_ui_asset_picker_intern.hh)
 * \{ */

Image *agent_ui_asset_pick_image(const bContext *C, const MixieAssetPick &pick)
{
  Main *bmain = CTX_data_main(C);
  if (!bmain || !pick.image[0]) {
    return nullptr;
  }
  /* Image IDs are "IM<name>": search from offset 2, as the chat's own
   * thumbnail blit does (`mixie_chat_ui_attachments.cc`). */
  return static_cast<Image *>(
      BLI_findstring(&bmain->images, pick.image, offsetof(ID, name) + 2));
}

void agent_ui_asset_pick_thumb(const bContext *C, const MixieAssetPick &pick, const rctf &box)
{
  if (Image *image = agent_ui_asset_pick_image(C, pick)) {
    pane_image_thumb_draw(image, box);
    return;
  }
  /* The Library's placeholder: a dim mesh glyph centred on the plate. */
  MIXAR_THEME_LOAD(col, TextSecondary);
  const float bg[4] = GEN_COL_TILE;
  const float s = std::min(BLI_rctf_size_x(&box), BLI_rctf_size_y(&box)) * 0.34f;
  rctf glyph;
  glyph.xmin = BLI_rctf_cent_x(&box) - s * 0.5f;
  glyph.xmax = glyph.xmin + s;
  glyph.ymin = BLI_rctf_cent_y(&box) - s * 0.5f;
  glyph.ymax = glyph.ymin + s;
  agent_ui_icon_draw(AGENT_ICON_MESH, &glyph, col, bg);
}

void agent_ui_asset_pick_type_label(const MixieAssetPick &pick, char r_out[32])
{
  const char c = pick.asset_type[0];
  const char *label = (c == 'c' || c == 'C') ? "Collection" :
                      (c == 'o' || c == 'O') ? "Object" :
                                               "Asset";
  BLI_strncpy(r_out, label, 32);
}

void agent_ui_asset_pick_match_label(const MixieAssetPick &pick,
                                     const bool with_word,
                                     char r_out[32])
{
  r_out[0] = '\0';
  if (!(pick.score >= 0.0f)) {
    return;
  }
  const int percent = std::clamp(int(pick.score * 100.0f + 0.5f), 0, 100);
  BLI_snprintf(r_out, 32, with_word ? "%d%% match" : "%d%%", percent);
}

void agent_ui_asset_pick_wrap(
    const char *text, const float max_w, const float font, char r_a[256], char r_b[256])
{
  r_a[0] = '\0';
  r_b[0] = '\0';
  if (!text || !text[0]) {
    return;
  }
  BLI_strncpy(r_a, text, 256);
  if (pane_text_width(r_a, font) <= max_w) {
    return;
  }
  /* Longest prefix that still fits, broken at a space (dropped) or after a
   * name separator (kept on the first line): library assets are named
   * "minotaur_sword_001", which a space-only break treated as one word. */
  const auto breakable = [](const char c) {
    return c == ' ' || c == '_' || c == '-' || c == '.' || c == '/';
  };
  int split = 0; /* Index of the break character. */
  for (int i = 1; r_a[i] && r_a[i + 1]; i++) {
    if (!breakable(r_a[i])) {
      continue;
    }
    const size_t keep = r_a[i] == ' ' ? size_t(i) : size_t(i) + 1;
    char probe[256];
    BLI_strncpy(probe, r_a, keep + 1);
    if (pane_text_width(probe, font) > max_w) {
      break;
    }
    split = i;
  }
  if (split == 0) {
    /* One unbreakable run: a single fitted line reads better than a cut. */
    pane_fit_text(r_a, 256, max_w, font);
    return;
  }
  BLI_strncpy(r_b, r_a + split + 1, 256);
  r_a[r_a[split] == ' ' ? split : split + 1] = '\0';
  pane_fit_text(r_b, 256, max_w, font);
}

void agent_ui_asset_pick_answer_button(ui::Block *block,
                                       const rctf &rect,
                                       const MixieAssetPicker &picker,
                                       const char *value,
                                       const char *tip)
{
  if (!value || !value[0] || BLI_rctf_size_x(&rect) < 1.0f || BLI_rctf_size_y(&rect) < 1.0f) {
    return;
  }
  ui::Button *but = uiDefButO(block,
                              ui::ButtonType::But,
                              "mixie_chat.select_slot_action",
                              blender::wm::OpCallContext::InvokeDefault,
                              "",
                              int(rect.xmin),
                              int(rect.ymin),
                              short(BLI_rctf_size_x(&rect)),
                              short(BLI_rctf_size_y(&rect)),
                              tip);
  if (but) {
    PointerRNA *op_ptr = ui::button_operator_ptr_ensure(but);
    RNA_string_set(op_ptr, "bubble_id", picker.bubble_id);
    RNA_string_set(op_ptr, "action_value", value);
  }
}

/** \} */

namespace {

/** The question as one plain line: markdown emphasis and line breaks are
 * the transcript's business, not a header's. */
void flatten_question(const char *src, char r_out[512])
{
  int n = 0;
  bool line_start = true;
  for (const char *p = src; *p && n < 511; p++) {
    char ch = *p;
    if (ch == '\n' || ch == '\r' || ch == '\t') {
      ch = ' ';
    }
    if (ch == '*' || ch == '`' || (line_start && ch == '#')) {
      continue;
    }
    if (ch == ' ' && (n == 0 || r_out[n - 1] == ' ')) {
      line_start = true;
      continue;
    }
    line_start = (ch == ' ');
    r_out[n++] = ch;
  }
  while (n > 0 && r_out[n - 1] == ' ') {
    n--;
  }
  r_out[n] = '\0';
}

}  // namespace

void agent_ui_asset_picker_draw(const bContext *C,
                                ARegion *region,
                                const rctf &panel,
                                const float u,
                                const MixieAssetPicker &picker)
{
  if (picker.count <= 0) {
    return;
  }
  char question[512];
  flatten_question(picker.question, question);
  if (!question[0]) {
    BLI_strncpy(question, "Which asset from your library should I use?", sizeof(question));
  }

  PickResolveInput in{};
  in.base = agent_ui_generations_input(panel, u);
  in.cancel_label = picker.cancel_value[0] ?
                        pane_text_width(PICK_CANCEL_LABEL, in.base.font_chip) :
                        0.0f;
  in.action_primary = pane_text_width(PICK_ACTION_PRIMARY, in.base.font_action);
  in.action_secondary = pane_text_width(PICK_ACTION_SECONDARY, in.base.font_action);
  in.count = picker.count;
  in.question_lines = 1;
  in.name_lines = 1;
  PickFrame frame = agent_ui_asset_picker_resolve(in);
  /* Measure against the frame the counts produced, then resolve again: the
   * question at the chip font in its header slot, the names at the caption
   * font in the tile. A taller caption can only shrink the tile, so the
   * second pass settles. */
  for (int pass = 0; pass < 2; pass++) {
    const int question_lines = pane_text_width(question, frame.gen.font_chip) >
                                       frame.question.xmax - frame.question.xmin ?
                                   2 :
                                   1;
    const float inset = std::min(frame.gen.cap_inset, frame.tile * 0.12f);
    const float text_w = std::max(1.0f, frame.tile - 2.0f * inset);
    int name_lines = 1;
    for (int i = 0; i < frame.count && i < picker.count; i++) {
      if (pane_text_width(picker.picks[i].asset_name, frame.gen.font_cap) > text_w) {
        name_lines = 2;
        break;
      }
    }
    if (question_lines == in.question_lines && name_lines == in.name_lines) {
      break;
    }
    in.question_lines = question_lines;
    in.name_lines = name_lines;
    frame = agent_ui_asset_picker_resolve(in);
  }
  const GenFrame &g = frame.gen;

  MIXAR_THEME_LOAD(text, Text);
  MIXAR_THEME_LOAD(strong, TextStrong);
  MIXAR_THEME_LOAD(dim, TextSecondary);
  const float chip_off[4] = GEN_COL_CHIP_OFF;
  const float tile_bg[4] = GEN_COL_TILE;

  GPU_blend(GPU_BLEND_ALPHA);
  pane_wash_paint(panel, u);

  /* The Library's detail divider. */
  const float div_inset = std::max(GEN_DIVIDER_INSET * u, g.pad * 0.5f);
  pane_column_divider(g.detail_div_x, panel.ymin + div_inset, panel.ymax - div_inset, u);

  /* ---- Header: the agent's question, then Cancel in the sort-chip slot. ---- */
  const rctf qbox = gen_rct(frame.question);
  {
    char line_a[256];
    char line_b[256];
    agent_ui_asset_pick_wrap(question, BLI_rctf_size_x(&qbox), g.font_chip, line_a, line_b);
    const float pitch = g.font_chip * 1.35f;
    const float lines = line_b[0] ? 2.0f : 1.0f;
    const float first_cy = BLI_rctf_cent_y(&qbox) + (lines - 1.0f) * pitch * 0.5f;
    pane_label_left(line_a, qbox.xmin, first_cy, g.font_chip, strong);
    if (line_b[0]) {
      pane_label_left(line_b, qbox.xmin, first_cy - pitch, g.font_chip, strong);
    }
  }
  const rctf cancel_rect = gen_rct(frame.cancel);
  const bool has_cancel = BLI_rctf_size_x(&cancel_rect) > 0.0f;
  if (has_cancel) {
    pane_fill_round(&cancel_rect, std::min(g.chip_r, BLI_rctf_size_y(&cancel_rect) * 0.5f), chip_off);
    char label[32];
    BLI_strncpy(label, PICK_CANCEL_LABEL, sizeof(label));
    pane_fit_text(label, std::max(1.0f, BLI_rctf_size_x(&cancel_rect) - g.pad), g.font_chip);
    pane_label_centre(label,
                      BLI_rctf_cent_x(&cancel_rect),
                      BLI_rctf_cent_y(&cancel_rect),
                      g.font_chip,
                      dim);
  }

  /* ---- Tiles: plate, preview, two-line caption — the Library's tile. ---- */
  const rctf view = gen_rct(frame.view);
  const int selected = std::clamp(picker.selected, 0, picker.count - 1);
  const float font_cap = g.font_cap;
  {
    const GenViewportClip clip(view);
    for (int i = 0; i < frame.count && i < picker.count; i++) {
      const MixieAssetPick &pick = picker.picks[i];
      const rctf tile = gen_rct(frame.tiles[i]);
      pane_fill_round(&tile, std::min(GEN_TILE_RADIUS * u, frame.tile * 0.18f), tile_bg);
      agent_ui_asset_pick_thumb(C, pick, tile);

      const float inset = std::min(g.cap_inset, frame.tile * 0.12f);
      const float text_w = std::max(1.0f, frame.tile - 2.0f * inset);
      const float cap1 = tile.ymin - g.cap_gap - font_cap * 0.5f;
      const float cap2 = cap1 - font_cap * 1.35f;

      char type_label[32];
      agent_ui_asset_pick_type_label(pick, type_label);
      char match[32];
      agent_ui_asset_pick_match_label(pick, false, match);
      const float match_w = match[0] ? pane_text_width(match, font_cap) : 0.0f;
      pane_fit_text(type_label,
                    std::max(1.0f, match_w > 0.0f ? text_w - match_w - g.gap * 0.65f : text_w),
                    font_cap);
      pane_label_left(type_label, tile.xmin + inset, cap1, font_cap, dim);
      if (match[0]) {
        pane_label_right(match, tile.xmax - inset, cap1, font_cap, dim);
      }
      /* The name on the caption's remaining line(s): wrapped at a separator
       * when the frame reserved two, ellipsised only past that. */
      char name_a[256];
      char name_b[256];
      if (in.name_lines >= 2) {
        agent_ui_asset_pick_wrap(pick.asset_name, text_w, font_cap, name_a, name_b);
      }
      else {
        BLI_strncpy(name_a, pick.asset_name, sizeof(name_a));
        pane_fit_text(name_a, text_w, font_cap);
        name_b[0] = '\0';
      }
      pane_label_left(name_a, tile.xmin + inset, cap2, font_cap, text);
      if (name_b[0]) {
        pane_label_left(name_b, tile.xmin + inset, cap2 - font_cap * 1.35f, font_cap, text);
      }
    }
  }

  /* ---- Controls: one unembossed block over the painted surface. ---- */
  ui::Block *block = ui::block_begin(
      C, region, AGENT_ASSET_PICKER_BLOCK, blender::ui::EmbossType::None);

  for (int i = 0; i < frame.count && i < picker.count; i++) {
    const MixieAssetPick &pick = picker.picks[i];
    const rctf tile = gen_rct(frame.tiles[i]);
    rctf hit;
    if (!BLI_rctf_isect(&tile, &view, &hit) || BLI_rctf_size_y(&hit) < 1.0f) {
      continue;
    }
    /* Selecting is the Library's stock context operator, on a PreviewTile —
     * the button family whose press survives to start a drag (agent-bubble
     * doc); answering is the detail column's "Use This Asset"; and DRAGGING
     * the tile into a 3D viewport places the pick where it lands and answers
     * with it (`space_mixie_chat/mixie_chat_asset_picker_drop.cc`), as a
     * Library tile does. */
    ui::Button *but = uiDefIconPreviewBut(block,
                                          ui::ButtonType::PreviewTile,
                                          ICON_NONE,
                                          int(hit.xmin),
                                          int(hit.ymin),
                                          short(BLI_rctf_size_x(&hit)),
                                          short(BLI_rctf_size_y(&hit)),
                                          nullptr,
                                          0.0f,
                                          0.0f,
                                          "Click to inspect this match, or drag it into the viewport");
    if (!but) {
      continue;
    }
    if (wmOperatorType *ot = WM_operatortype_find("wm.context_set_string", true)) {
      ui::button_operator_set(but, ot, blender::wm::OpCallContext::InvokeDefault);
    }
    pane_but_tooltip_owned(but,
                           (std::string(pick.asset_name) +
                            " \xE2\x80\x94 click to inspect, or drag into the viewport")
                               .c_str());
    PointerRNA *op_ptr = ui::button_operator_ptr_ensure(but);
    RNA_string_set(op_ptr, "data_path", "window_manager." MIXIE_ASSET_PICKER_SELECTED_PROP);
    RNA_string_set(op_ptr, "value", pick.value);

    /* The drag: a name payload the View3D's Mixie dropbox recognises, owned
     * by the drag once it starts (the moodboard's template drag). The tile's
     * own preview rides along as the drag image; the ImBuf is the image
     * cache's, which outlives the drag as long as the picker's image does. */
    ui::button_drag_set_name(
        but, BLI_strdup((std::string(MIXIE_ASSET_PICK_DRAG_PREFIX) + pick.value).c_str()));
    ui::button_dragflag_enable(but, ui::BUT_DRAGPOIN_FREE | ui::BUT_DRAG_FULL_BUT);
    if (Image *image = agent_ui_asset_pick_image(C, pick)) {
      void *lock = nullptr;
      ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
      if (ibuf && ibuf->byte_data() && ibuf->x > 0 && ibuf->y > 0) {
        but->imb = ibuf;
        but->imb_scale = frame.tile / float(std::max(ibuf->x, ibuf->y));
      }
      BKE_image_release_ibuf(image, ibuf, lock);
    }
  }
  if (has_cancel) {
    agent_ui_asset_pick_answer_button(
        block, cancel_rect, picker, picker.cancel_value, "Stop and don't use a library asset");
  }

  /* The detail column paints AND lays its actions, so it runs while blend is
   * still on and before the block is closed. */
  agent_ui_asset_picker_detail(C, block, panel, frame, picker);

  GPU_blend(GPU_BLEND_NONE);

  ui::block_end(C, block);
  ui::block_draw(C, block);

  /* Selection ring last, clipped with the tiles — the Library's ring. */
  if (selected < frame.count) {
    const GenViewportClip clip(view);
    MIXAR_THEME_LOAD(accent, AgentAccent);
    const float w = std::max(GEN_SEL_BORDER * u, g.pad * 0.2f);
    rctf ring = gen_rct(frame.tiles[selected]);
    BLI_rctf_pad(&ring, -w * 0.5f, -w * 0.5f);
    GPU_blend(GPU_BLEND_ALPHA);
    ui::draw_roundbox_corner_set(ui::CNR_ALL);
    ui::draw_roundbox_4fv_ex(&ring,
                             nullptr,
                             nullptr,
                             1.0f,
                             accent,
                             w,
                             std::min(GEN_TILE_RADIUS * u, frame.tile * 0.18f) - w * 0.5f);
    GPU_blend(GPU_BLEND_NONE);
  }
}

}  // namespace blender
