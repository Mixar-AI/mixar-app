/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Project-rules overlay — shared helpers: the RNA bridge to the
 * Python-owned properties (WindowManager.mixie_chat_rules_visible + the
 * mixie_chat_rule_entries mirror), the operator dispatch used for every
 * data mutation, greedy word-wrap line layout, and caret geometry used by
 * both the draw (mixie_chat_rules_overlay.cc) and event
 * (mixie_chat_rules_events.cc) halves.
 */

#include <algorithm>
#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_string_utf8.h"

#include "BLF_api.hh"

#include "BKE_context.hh"

#include "DNA_windowmanager_types.h"

#include "ED_screen.hh"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "RNA_access.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_intern.hh"
#include "mixie_chat_rules_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name RNA Bridge (Python-owned properties)
 * \{ */

/** Bounded read of a Python-registered RNA string property. */
static void rules_read_string(PointerRNA *ptr, PropertyRNA *prop, char *buf, int buf_maxncpy)
{
  buf[0] = '\0';
  if (!prop) {
    return;
  }
  char fixed[256];
  int len = 0;
  char *value = RNA_property_string_get_alloc(ptr, prop, fixed, sizeof(fixed), &len);
  if (value) {
    BLI_strncpy_utf8(buf, value, size_t(buf_maxncpy));
    if (value != fixed) {
      MEM_delete_void(value);
    }
  }
}

bool mixie_chat_rules_read_visible(wmWindowManager *wm)
{
  if (!wm) {
    return false;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *prop = RNA_struct_find_property(&wm_ptr, "mixie_chat_rules_visible");
  if (!prop) {
    return false;
  }
  return RNA_property_boolean_get(&wm_ptr, prop);
}

void mixie_chat_rules_set_visible(bContext *C, bool visible)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm) {
    return;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *prop = RNA_struct_find_property(&wm_ptr, "mixie_chat_rules_visible");
  if (!prop) {
    return;
  }
  RNA_property_boolean_set(&wm_ptr, prop, visible);
  /* Every chat surface (editor + floating bubble) shows the overlay —
   * repaint them all via the space notifier the listener already handles. */
  WM_main_add_notifier(NC_SPACE | ND_SPACE_MIXIE_CHAT, nullptr);
}

void mixie_chat_rules_read_entries(wmWindowManager *wm,
                                   blender::Vector<RuleDrawEntry> &r_items)
{
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *entries_prop = RNA_struct_find_property(&wm_ptr, "mixie_chat_rule_entries");
  if (!entries_prop) {
    return;
  }

  PropertyRNA *p_text = nullptr;
  PropertyRNA *p_enabled = nullptr;
  PropertyRNA *p_global = nullptr;

  CollectionPropertyIterator iter;
  RNA_property_collection_begin(&wm_ptr, entries_prop, &iter);
  for (; iter.valid; RNA_property_collection_next(&iter)) {
    PointerRNA item_ptr = iter.ptr;
    if (!p_text) {
      /* All items share one runtime StructRNA — resolve once. */
      p_text = RNA_struct_find_property(&item_ptr, "text");
      p_enabled = RNA_struct_find_property(&item_ptr, "enabled");
      p_global = RNA_struct_find_property(&item_ptr, "is_global");
    }
    RuleDrawEntry entry;
    rules_read_string(&item_ptr, p_text, entry.text, sizeof(entry.text));
    entry.enabled = p_enabled ? RNA_property_boolean_get(&item_ptr, p_enabled) : true;
    entry.is_global = p_global ? RNA_property_boolean_get(&item_ptr, p_global) : false;
    if (entry.text[0] != '\0') {
      r_items.append(entry);
    }
  }
  RNA_property_collection_end(&iter);
}

void mixie_chat_rules_dispatch_op(
    bContext *C, ARegion *region, const char *op_idname, int index, const char *text)
{
  wmOperatorType *ot = WM_operatortype_find(op_idname, true);
  if (!ot) {
    return;
  }
  PointerRNA op_ptr = WM_operator_properties_create_ptr(ot);
  if (index >= 0) {
    RNA_int_set(&op_ptr, "index", index);
  }
  if (text != nullptr) {
    RNA_string_set(&op_ptr, "text", text);
  }
  WM_operator_name_call_ptr(
      C, ot, blender::wm::OpCallContext::ExecDefault, &op_ptr, nullptr);
  WM_operator_properties_free(&op_ptr);
  ED_region_tag_redraw(region);
}

void mixie_chat_rules_reset_runtime(MixieChatRuntime *rt)
{
  rt->rules_lines.clear();
  rt->rules_rows.clear();
  BLI_rctf_init(&rt->rules_panel_bounds, 0.0f, 0.0f, 0.0f, 0.0f);
  BLI_rctf_init(&rt->rules_text_bounds, 0.0f, 0.0f, 0.0f, 0.0f);
  BLI_rctf_init(&rt->rules_close_bounds, 0.0f, 0.0f, 0.0f, 0.0f);
  BLI_rctf_init(&rt->rules_list_bounds, 0.0f, 0.0f, 0.0f, 0.0f);
  BLI_rctf_init(&rt->rules_submit_bounds, 0.0f, 0.0f, 0.0f, 0.0f);
  rt->rules_close_hovered = false;
  rt->rules_submit_hovered = false;
  rt->rules_content_h = 0.0f;
  rt->rules_view_h = 0.0f;
  rt->rules_caret_goal_x = -1.0f;
  rt->rules_sel_anchor = -1;
  rt->rules_sel_dragging = false;
  rt->rules_editing_index = -1;
  rt->rules_confirm_delete = -1;
  rt->rules_editor_scroll = 0.0f;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Line Layout (greedy word wrap)
 * \{ */

int mixie_chat_rules_wrap_text(const char *text,
                               int font_id,
                               int font_px,
                               float wrap_w,
                               blender::Vector<RulesLineSpan> &r_lines)
{
  r_lines.clear();
  if (wrap_w <= 0.0f || font_px <= 0) {
    return 0;
  }
  BLF_size(font_id, float(font_px));

  const int total = int(strlen(text));
  int pos = 0;
  float top = 0.0f;

  for (;;) {
    int i = pos;
    int last_space = -1; /* byte offset AFTER a breakable space */
    int line_end = -1;
    bool hard_break = false;

    while (i < total) {
      if (text[i] == '\n') {
        line_end = i;
        hard_break = true;
        break;
      }
      const int char_len = std::max(1, BLI_str_utf8_size_safe(text + i));
      const int next = i + char_len;
      if (i > pos && BLF_width(font_id, text + pos, size_t(next - pos)) > wrap_w) {
        /* Wrap before this character; prefer the last space boundary. */
        line_end = (last_space > pos) ? last_space : i;
        break;
      }
      if (text[i] == ' ') {
        last_space = next;
      }
      i = next;
    }
    if (line_end < 0) {
      line_end = total;
    }

    RulesLineSpan span;
    span.start = pos;
    span.len = line_end - pos;
    span.top = top;
    r_lines.append(span);
    top += 1.0f; /* placeholder unit; caller multiplies by line height */

    if (hard_break) {
      pos = line_end + 1;
      if (pos > total) {
        break;
      }
      if (pos == total) {
        /* Trailing newline: an empty final line so the caret can sit on it. */
        r_lines.append({pos, 0, top});
        break;
      }
      continue;
    }
    if (line_end >= total) {
      break;
    }
    pos = line_end;
  }
  /* Spans carry line ORDINALS in .top (0, 1, 2, ...) — callers multiply
   * by their line height to get pixel offsets. */
  return int(r_lines.size());
}

float mixie_chat_rules_relayout(MixieChatRuntime *rt)
{
  const float line_h = rt->rules_line_h;
  if (rt->rules_wrap_w <= 0.0f || line_h <= 0.0f || rt->rules_text_px <= 0) {
    rt->rules_lines.clear();
    return 0.0f;
  }
  const int count = mixie_chat_rules_wrap_text(
      rt->rules_text, BLF_default(), rt->rules_text_px, rt->rules_wrap_w, rt->rules_lines);
  for (RulesLineSpan &span : rt->rules_lines) {
    span.top *= line_h;
  }
  /* NOTE: rules_content_h / rules_view_h describe the CARD LIST viewport
   * (wheel scrolling); the editor's own caret-follow offset is
   * rules_editor_scroll, clamped against the line count here. */
  return float(count) * line_h;
}

int mixie_chat_rules_line_of_offset(const MixieChatRuntime *rt, int cursor)
{
  const int count = int(rt->rules_lines.size());
  if (count == 0) {
    return 0;
  }
  for (int i = 0; i < count; i++) {
    const RulesLineSpan &line = rt->rules_lines[i];
    if (cursor <= line.start + line.len) {
      return i;
    }
  }
  return count - 1;
}

float mixie_chat_rules_offset_to_x(const MixieChatRuntime *rt, int line, int cursor)
{
  if (line < 0 || line >= int(rt->rules_lines.size())) {
    return 0.0f;
  }
  const RulesLineSpan &span = rt->rules_lines[line];
  const int in_line = std::clamp(cursor - span.start, 0, span.len);
  if (in_line <= 0) {
    return 0.0f;
  }
  const int font_id = BLF_default();
  BLF_size(font_id, float(rt->rules_text_px));
  return BLF_width(font_id, rt->rules_text + span.start, size_t(in_line));
}

int mixie_chat_rules_x_to_offset(const MixieChatRuntime *rt, int line, float x)
{
  if (line < 0 || line >= int(rt->rules_lines.size())) {
    return int(strlen(rt->rules_text));
  }
  const RulesLineSpan &span = rt->rules_lines[line];
  if (x <= 0.0f || span.len == 0) {
    return span.start;
  }
  const int font_id = BLF_default();
  BLF_size(font_id, float(rt->rules_text_px));

  const char *base = rt->rules_text + span.start;
  int offset = 0;
  float prev_w = 0.0f;
  while (offset < span.len) {
    const int char_len = std::max(1, BLI_str_utf8_size_safe(base + offset));
    const int next = std::min(offset + char_len, span.len);
    const float w = BLF_width(font_id, base, size_t(next));
    if (w >= x) {
      /* Snap to whichever side of the glyph is closer. */
      return span.start + ((x - prev_w < w - x) ? offset : next);
    }
    prev_w = w;
    offset = next;
  }
  return span.start + span.len;
}

void mixie_chat_rules_editor_follow_caret(MixieChatRuntime *rt, float view_h)
{
  if (rt->rules_lines.is_empty() || view_h <= 0.0f) {
    rt->rules_editor_scroll = 0.0f;
    return;
  }
  const int line = mixie_chat_rules_line_of_offset(rt, rt->rules_cursor);
  const float top = rt->rules_lines[line].top;
  const float bottom = top + rt->rules_line_h;
  if (top < rt->rules_editor_scroll) {
    rt->rules_editor_scroll = top;
  }
  else if (bottom > rt->rules_editor_scroll + view_h) {
    rt->rules_editor_scroll = bottom - view_h;
  }
  const float content_h = float(rt->rules_lines.size()) * rt->rules_line_h;
  const float max_scroll = std::max(0.0f, content_h - view_h);
  rt->rules_editor_scroll = std::clamp(rt->rules_editor_scroll, 0.0f, max_scroll);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Glyphs
 * \{ */

void rules_draw_edit_glyph(float cx, float cy, float half, const float color[4], float scale)
{
  /* Pencil at 45° pointing down-left: slim body (two parallel edges), a
   * cap at the top end, and a converging tip. */
  const float tipx = cx - half, tipy = cy - half;
  const float topx = cx + half, topy = cy + half;
  /* Half body thickness, offset perpendicular to the (1,1) direction. */
  const float px = -1.6f * scale * 0.7071f;
  const float py = 1.6f * scale * 0.7071f;
  /* Body starts a bit up from the tip so the tip converges to a point. */
  const float bx = tipx + half * 0.55f;
  const float by = tipy + half * 0.55f;

  GPUVertFormat *format = immVertexFormat();
  uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);

  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(color);
  GPU_line_width(1.2f * scale);

  immBegin(GPU_PRIM_LINES, 10);
  /* Body edges. */
  immVertex2f(pos, bx + px, by + py);
  immVertex2f(pos, topx + px, topy + py);
  immVertex2f(pos, bx - px, by - py);
  immVertex2f(pos, topx - px, topy - py);
  /* Top cap. */
  immVertex2f(pos, topx + px, topy + py);
  immVertex2f(pos, topx - px, topy - py);
  /* Tip. */
  immVertex2f(pos, tipx, tipy);
  immVertex2f(pos, bx + px, by + py);
  immVertex2f(pos, tipx, tipy);
  immVertex2f(pos, bx - px, by - py);
  immEnd();

  immUnbindProgram();
  GPU_line_width(1.0f);
}

/** \} */
}  // namespace blender
