/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Past-chats overlay — data + drawing helpers shared by the overlay's
 * draw (mixie_chat_history_overlay.cc) and event
 * (mixie_chat_history_events.cc) halves: RNA readers for the
 * Python-owned entry mirror, text measurement / ellipsis / label
 * drawing, the X glyph, and the operator dispatch bridge.
 */

#include <algorithm>
#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_string_utf8.h"
#include "BLI_vector.hh"

#include "BLF_api.hh"

#include "DNA_windowmanager_types.h"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "RNA_access.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "ED_screen.hh"

#include "mixie_chat_history_intern.hh"
#include "mixie_chat_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name RNA Readers (Python-owned WindowManager data)
 * \{ */

/** Bounded read of a Python-registered RNA string property. */
static void history_read_string(PointerRNA *ptr, PropertyRNA *prop, char *buf, int buf_maxncpy)
{
  buf[0] = '\0';
  if (!prop) {
    return;
  }
  char fixed[256];
  int len = 0;
  char *value = RNA_property_string_get_alloc(ptr, prop, fixed, sizeof(fixed), &len);
  if (value) {
    BLI_strncpy(buf, value, buf_maxncpy);
    if (value != fixed) {
      MEM_delete_void(static_cast<void *>(value));
    }
  }
}

bool mixie_chat_history_read_visible(wmWindowManager *wm)
{
  if (!wm) {
    return false;
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *prop = RNA_struct_find_property(&wm_ptr, "mixie_chat_history_visible");
  if (!prop) {
    return false;
  }
  return RNA_property_boolean_get(&wm_ptr, prop);
}

void mixie_chat_history_read_entries(wmWindowManager *wm,
                                     blender::Vector<HistoryDrawEntry> &r_items)
{
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *entries_prop = RNA_struct_find_property(&wm_ptr, "mixie_chat_history_entries");
  if (!entries_prop) {
    return;
  }

  PropertyRNA *p_name = nullptr;
  PropertyRNA *p_sid = nullptr;
  PropertyRNA *p_when = nullptr;
  PropertyRNA *p_group = nullptr;

  CollectionPropertyIterator iter;
  RNA_property_collection_begin(&wm_ptr, entries_prop, &iter);
  for (; iter.valid; RNA_property_collection_next(&iter)) {
    PointerRNA item_ptr = iter.ptr;
    if (!p_name) {
      /* All items share one runtime StructRNA — resolve once. */
      p_name = RNA_struct_find_property(&item_ptr, "name");
      p_sid = RNA_struct_find_property(&item_ptr, "session_id");
      p_when = RNA_struct_find_property(&item_ptr, "when");
      p_group = RNA_struct_find_property(&item_ptr, "group");
    }
    HistoryDrawEntry entry;
    history_read_string(&item_ptr, p_name, entry.title, sizeof(entry.title));
    history_read_string(&item_ptr, p_sid, entry.session_id, sizeof(entry.session_id));
    history_read_string(&item_ptr, p_when, entry.when, sizeof(entry.when));
    history_read_string(&item_ptr, p_group, entry.group, sizeof(entry.group));
    if (entry.session_id[0] != '\0') {
      r_items.append(entry);
    }
  }
  RNA_property_collection_end(&iter);
}

void mixie_chat_history_reset_runtime(MixieChatRuntime *rt)
{
  rt->history_rows.clear();
  BLI_rctf_init(&rt->history_panel_bounds, 0.0f, 0.0f, 0.0f, 0.0f);
  BLI_rctf_init(&rt->history_list_bounds, 0.0f, 0.0f, 0.0f, 0.0f);
  BLI_rctf_init(&rt->history_close_bounds, 0.0f, 0.0f, 0.0f, 0.0f);
  BLI_rctf_init(&rt->history_search_bounds, 0.0f, 0.0f, 0.0f, 0.0f);
  rt->history_close_hovered = false;
  rt->history_content_h = 0.0f;
  rt->history_view_h = 0.0f;
  rt->history_sel = -1;
  rt->history_confirm_id[0] = '\0';
}

void mixie_chat_history_dispatch_session_op(bContext *C,
                                            ARegion *region,
                                            const char *op_idname,
                                            const char *session_id)
{
  wmOperatorType *ot = WM_operatortype_find(op_idname, true);
  if (!ot || session_id[0] == '\0') {
    return;
  }
  PointerRNA op_ptr = WM_operator_properties_create_ptr(ot);
  RNA_string_set(&op_ptr, "session_id", session_id);
  WM_operator_name_call_ptr(
      C, ot, blender::wm::OpCallContext::ExecDefault, &op_ptr, nullptr);
  WM_operator_properties_free(&op_ptr);
  ED_region_tag_redraw(region);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Text + Glyph Helpers
 * \{ */

void hist_draw_label(
    const char *text, int font_id, int font_px, float x, float baseline_y, const float color[4])
{
  BLF_size(font_id, float(font_px));
  BLF_color4fv(font_id, color);
  BLF_position(font_id, x, baseline_y, 0.0f);
  BLF_draw(font_id, text, strlen(text));
  /* BLF can leave a different blend mode behind; every translucent fill
   * drawn after a label (divider, hover wash, delete ring, scroll thumb)
   * needs alpha blending back or it renders fully opaque. */
  GPU_blend(GPU_BLEND_ALPHA);
}

float hist_text_width(const char *text, int font_id, int font_px)
{
  BLF_size(font_id, float(font_px));
  return BLF_width(font_id, text, strlen(text));
}

/** Clip `src` to `max_width` px (font already implied by `font_px`),
 * appending a UTF-8 ellipsis when trimmed. The chat primitives only wrap
 * (never truncate), so list rows need their own single-line clipper. */
void hist_text_ellipsis(
    const char *src, int font_id, int font_px, float max_width, char *dst, size_t dst_size)
{
  BLF_size(font_id, float(font_px));
  const size_t len = strlen(src);
  if (BLF_width(font_id, src, len) <= max_width) {
    BLI_strncpy(dst, src, dst_size);
    return;
  }
  const char *ellipsis = "\xe2\x80\xa6"; /* U+2026 */
  const float ellipsis_w = BLF_width(font_id, ellipsis, 3);
  size_t keep = 0;
  while (keep < len) {
    const size_t step = size_t(std::max(1, BLI_str_utf8_size_safe(src + keep)));
    const size_t next = keep + step;
    if (next >= len || next + 4 >= dst_size) {
      break;
    }
    if (BLF_width(font_id, src, next) + ellipsis_w > max_width) {
      break;
    }
    keep = next;
  }
  memcpy(dst, src, keep);
  dst[keep] = '\0';
  BLI_strncpy(dst + keep, ellipsis, dst_size - keep);
}

void hist_draw_x_glyph(float cx, float cy, float half, const float color[4], float scale)
{
  GPUVertFormat *format = immVertexFormat();
  uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);

  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(color);
  GPU_line_width(1.5f * scale);

  immBegin(GPU_PRIM_LINES, 4);
  immVertex2f(pos, cx - half, cy - half);
  immVertex2f(pos, cx + half, cy + half);
  immVertex2f(pos, cx - half, cy + half);
  immVertex2f(pos, cx + half, cy - half);
  immEnd();

  immUnbindProgram();
  GPU_line_width(1.0f);
}

/** \} */
}  // namespace blender
