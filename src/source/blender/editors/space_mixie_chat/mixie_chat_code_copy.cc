/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Copy chips on markdown code blocks.
 *
 * The agent's code answers render as markdown code cards, which the
 * character-level text selection cannot map onto (selection offsets index
 * the raw markdown, not the laid-out segments). Each code card therefore
 * carries its own copy chip in the top-right corner that puts the block's
 * raw code on the system clipboard.
 *
 * Wiring: the messages render pass calls mixie_chat_code_hits_reset() and
 * brackets each chat_ui_draw_markdown call with set_message(); the markdown
 * segment loop reports the segment index via set_segment(); draw_code_block
 * calls mixie_chat_code_chip_draw() which draws the chip AND registers its
 * hit rect (draw geometry and click region share one definition). Clicks
 * arrive from mixie_chat_ui_handler / the select-text keymap operator, both
 * of which already run for SPACE_MIXIE_CHAT and SPACE_AGENT_BUBBLE.
 *
 * Hits store (message_index, seg_index), never the code text — a click
 * re-resolves the text from the message metadata through the markdown parse
 * cache, so the per-draw rebuild allocates nothing.
 */

#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_rect.h"
#include "BLI_time.h"

#include "BKE_context.hh"

#include "DNA_scene_types.h"
#include "DNA_space_types.h"

#include "RNA_access.hh"

#include "ED_screen.hh"

#include "UI_view2d.hh"

#include "WM_api.hh"

#include "mixie_chat_intern.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* Chip geometry (unscaled px). */
#define CODE_CHIP_SIZE 18.0f
#define CODE_CHIP_MARGIN 4.0f
#define CODE_CHIP_FEEDBACK_SECONDS 1.5

/* Collector state — main-thread only, valid during one draw pass. */
static MixieChatRuntime *g_collect_rt = nullptr;
static int g_collect_msg = -1;
static int g_collect_seg = -1;

/* Hover + copied-feedback state. Shared across chat surfaces (docked chat
 * and Agent Bubble draw the same conversation; there is one cursor). */
static int g_hover_msg = -1;
static int g_hover_seg = -1;
static int g_feedback_msg = -1;
static int g_feedback_seg = -1;
static double g_feedback_time = 0.0;

static SpaceMixieChat *get_space_mixie_chat(const bContext *C)
{
  ScrArea *area = CTX_wm_area(C);
  /* SPACE_AGENT_BUBBLE has a layout-compatible spacedata struct. */
  if (area && (area->spacetype == SPACE_MIXIE_CHAT ||
               area->spacetype == SPACE_AGENT_BUBBLE))
  {
    return static_cast<SpaceMixieChat *>(area->spacedata.first);
  }
  return nullptr;
}

/* -------------------------------------------------------------------- */
/** \name Collector
 * \{ */

void mixie_chat_code_hits_reset(MixieChatRuntime *rt)
{
  if (rt) {
    rt->code_copy_hits.clear();
    rt->md_seg_hits.clear();
  }
  g_collect_rt = rt;
  g_collect_msg = -1;
  g_collect_seg = -1;
}

void mixie_chat_md_seg_record(const rctf *text_rect, bool mono, int font_size)
{
  if (!g_collect_rt || g_collect_msg < 0 || g_collect_seg < 0) {
    return;
  }
  MarkdownSegHit hit;
  hit.text_rect = *text_rect;
  hit.message_index = g_collect_msg;
  hit.seg_index = g_collect_seg;
  hit.mono = mono;
  hit.font_size = font_size;
  g_collect_rt->md_seg_hits.append(hit);
}

bool mixie_chat_md_seg_find(MixieChatRuntime *rt,
                            int message_index,
                            int seg_index,
                            MarkdownSegHit *r_hit)
{
  if (!rt) {
    return false;
  }
  for (const MarkdownSegHit &hit : rt->md_seg_hits) {
    if (hit.message_index == message_index && hit.seg_index == seg_index) {
      *r_hit = hit;
      return true;
    }
  }
  return false;
}

void mixie_chat_code_hits_set_message(int message_index)
{
  g_collect_msg = message_index;
  g_collect_seg = -1;
}

void mixie_chat_code_hits_set_segment(int seg_index)
{
  g_collect_seg = seg_index;
}

static bool code_copy_feedback_active(int msg, int seg)
{
  if (g_feedback_msg != msg || g_feedback_seg != seg) {
    return false;
  }
  return (BLI_time_now_seconds() - g_feedback_time) < CODE_CHIP_FEEDBACK_SECONDS;
}

bool mixie_chat_code_copy_feedback_pending()
{
  if (g_feedback_msg < 0) {
    return false;
  }
  if ((BLI_time_now_seconds() - g_feedback_time) < CODE_CHIP_FEEDBACK_SECONDS) {
    return true;
  }
  g_feedback_msg = -1;
  g_feedback_seg = -1;
  return false;
}

void mixie_chat_code_chip_draw(float right_x, float top_y, float scale_factor, int font_size)
{
  /* Only buttons drawn through an active collector are interactive — guards
   * against any future markdown draw outside the messages pass. */
  if (!g_collect_rt || g_collect_msg < 0 || g_collect_seg < 0) {
    return;
  }

  const bool copied = code_copy_feedback_active(g_collect_msg, g_collect_seg);
  const bool hovered = (g_hover_msg == g_collect_msg && g_hover_seg == g_collect_seg);

  /* A quiet text button in the card's header row — no permanent box; a
   * subtle rounded pill appears on hover only. Sized from the CODE FONT
   * SIZE, not scale_factor: the markdown draw path always passes
   * scale_factor 1.0, so px constants scaled by it ignore the UI scale and
   * the label came out illegibly small on scaled displays. */
  const char *label = copied ? "Copied \xE2\x9C\x94" : "Copy";
  int label_size = int(float(font_size) * 0.95f);
  if (label_size < 12) {
    label_size = 12;
  }
  float label_w, label_h;
  chat_ui_calc_text_bounds(label, 40.0f * float(label_size), label_size, 0, &label_w, &label_h);

  const float pad_x = float(label_size) * 0.55f;
  const float pad_y = float(label_size) * 0.25f;
  const float margin = CODE_CHIP_MARGIN * scale_factor;

  rctf btn;
  btn.xmax = right_x - margin;
  btn.xmin = btn.xmax - label_w - pad_x * 2.0f;
  btn.ymax = top_y - margin;
  btn.ymin = btn.ymax - label_h - pad_y * 2.0f;

  if (hovered && !copied) {
    float bg[4];
    chat_ui_get_button_hover_color(bg);
    chat_ui_draw_rounded_rect(&btn, 4.0f * scale_factor, bg);
  }

  float label_color[4];
  if (copied) {
    label_color[0] = 0.3f;
    label_color[1] = 0.8f;
    label_color[2] = 0.4f;
    label_color[3] = 1.0f;
  }
  else {
    chat_ui_get_button_text_color(label_color);
    /* Slightly dimmed until hovered, like the language label beside it. */
    label_color[3] = hovered ? 1.0f : 0.85f;
  }

  /* chat_ui_draw_label takes the baseline y; center the label box. */
  chat_ui_draw_label(label,
                     btn.xmin + pad_x,
                     (btn.ymin + btn.ymax) * 0.5f - label_h * 0.4f,
                     label_size,
                     0,
                     label_color,
                     false);

  CodeCopyHit hit;
  hit.bounds = btn;
  hit.message_index = g_collect_msg;
  hit.seg_index = g_collect_seg;
  g_collect_rt->code_copy_hits.append(hit);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Hover
 * \{ */

bool mixie_chat_code_hits_hover(MixieChatRuntime *rt,
                                float view_x,
                                float view_y,
                                bool *r_changed)
{
  int msg = -1, seg = -1;
  if (rt) {
    for (const CodeCopyHit &hit : rt->code_copy_hits) {
      if (BLI_rctf_isect_pt(&hit.bounds, view_x, view_y)) {
        msg = hit.message_index;
        seg = hit.seg_index;
        break;
      }
    }
  }
  if (r_changed) {
    *r_changed = (msg != g_hover_msg || seg != g_hover_seg);
  }
  g_hover_msg = msg;
  g_hover_seg = seg;
  return msg >= 0;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Click Dispatch
 * \{ */

const char *mixie_chat_message_segment_text(const bContext *C,
                                            int message_index,
                                            int seg_index,
                                            bool code_only)
{
  Scene *scene = CTX_data_scene(C);
  if (!scene) {
    return nullptr;
  }

  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *prop = RNA_struct_find_property(&scene_ptr, "mixie_chat_messages");
  if (!prop) {
    return nullptr;
  }

  PointerRNA msg_ptr{};
  if (!RNA_property_collection_lookup_int(&scene_ptr, prop, message_index, &msg_ptr)) {
    return nullptr;
  }

  PropertyRNA *meta_prop = RNA_struct_find_property(&msg_ptr, "metadata");
  if (!meta_prop) {
    return nullptr;
  }
  const int meta_len = RNA_property_string_length(&msg_ptr, meta_prop);
  if (meta_len <= 0) {
    return nullptr;
  }

  char *meta_buf = static_cast<char *>(
      MEM_new_uninitialized(size_t(meta_len) + 1, "code_copy_meta"));
  RNA_property_string_get(&msg_ptr, meta_prop, meta_buf);
  /* The parse cache keys on content, so the text stays valid after the
   * buffer is freed (it points into the cached segments). */
  const char *text = chat_ui_markdown_segment_text(meta_buf, seg_index, code_only);
  MEM_delete_void(static_cast<void *>(meta_buf));
  return text;
}

bool mixie_chat_handle_code_copy_click(bContext *C,
                                       ARegion *region,
                                       float mouse_x,
                                       float mouse_y)
{
  SpaceMixieChat *smixie = get_space_mixie_chat(C);
  if (!smixie) {
    return false;
  }
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);

  float view_x, view_y;
  ui::view2d_region_to_view(&region->v2d, int(mouse_x), int(mouse_y), &view_x, &view_y);

  for (const CodeCopyHit &hit : rt->code_copy_hits) {
    if (!BLI_rctf_isect_pt(&hit.bounds, view_x, view_y)) {
      continue;
    }
    const char *code = mixie_chat_message_segment_text(
        C, hit.message_index, hit.seg_index, /*code_only=*/true);
    if (code && code[0] != '\0') {
      WM_clipboard_text_set(code, false);
      g_feedback_msg = hit.message_index;
      g_feedback_seg = hit.seg_index;
      g_feedback_time = BLI_time_now_seconds();
    }
    ED_region_tag_redraw(region);
    return true;
  }

  return false;
}

/** \} */

}  // namespace blender
