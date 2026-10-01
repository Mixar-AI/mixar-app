/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

/* Included by rna_wm_mixar.cc in makesrna and generated runtime wrappers. */
#include "RNA_enum_types.hh"
#ifdef RNA_RUNTIME
#  include "BKE_context.hh"
#  include "BLI_string.h"
#  include "BLI_string_utf8.h"
#endif

namespace blender {
#ifdef RNA_RUNTIME
static bool rna_ui_begin(wmWindowManager *wm, const char *owner)
{
  return Mixar_ui_control_begin(wm, owner);
}
static void rna_ui_end(wmWindowManager *wm, const char *owner)
{
  Mixar_ui_control_end(wm, owner);
}
static void rna_ui_enable(wmWindowManager *wm, bool enabled)
{
  Mixar_ui_control_enable(wm, enabled);
}
static int rna_ui_generation(wmWindowManager *wm)
{
  return Mixar_ui_control_generation(wm);
}
static int rna_ui_pending(wmWindowManager * /*wm*/)
{
  return Mixar_ui_control_pending();
}
static int rna_ui_modal_count(wmWindow *win)
{
  return Mixar_ui_control_modal_count(win);
}

static bool rna_ui_event(wmWindow *win, bContext *C, ReportList *reports,
                         const char *owner, int type, int value, const char *text,
                         int x, int y, bool shift, bool ctrl, bool alt, bool oskey)
{
  if (!ELEM(value, KM_PRESS, KM_RELEASE, KM_NOTHING, KM_DBL_CLICK) ||
      (ISKEYBOARD_OR_BUTTON(type) && !ELEM(value, KM_PRESS, KM_RELEASE, KM_DBL_CLICK)) ||
      (value == KM_DBL_CLICK && !ISMOUSE_BUTTON(type)) ||
      (ISMOUSE_MOTION(type) && value != KM_NOTHING))
  {
    BKE_report(reports, RPT_ERROR, "Invalid UI event value");
    return false;
  }
  if (text && text[0]) {
    const int length = BLI_str_utf8_size_or_error(text);
    if (length < 1 || text[length] || value != KM_PRESS) {
      BKE_report(reports, RPT_ERROR, "UI text events require one UTF-8 character");
      return false;
    }
  }
  wmEvent event = *win->runtime->eventstate;
  event.type = wmEventType(type);
  event.val = value;
  event.flag = eWM_EventFlag(0);
  event.custom = 0;
  event.customdata = nullptr;
  event.customdata_free = false;
  event.xy[0] = x;
  event.xy[1] = y;
  event.modifier = wmEventModifierFlag(0);
  if (shift) { event.modifier |= KM_SHIFT; }
  if (ctrl) { event.modifier |= KM_CTRL; }
  if (alt) { event.modifier |= KM_ALT; }
  if (oskey) { event.modifier |= KM_OSKEY; }
  event.utf8_buf[0] = '\0';
  if (text && text[0]) { STRNCPY(event.utf8_buf, text); }
  WM_event_tablet_data_default_set(&event.tablet);
  return Mixar_ui_control_input(CTX_wm_manager(C), win, owner, &event);
}

static bool rna_ui_capture(wmWindow *win, bContext *C, ReportList *reports,
                           const char *filepath, int x, int y, int width, int height)
{
  if (Mixar_window_resize_dispatch_active()) {
    BKE_report(reports, RPT_ERROR, "Wait for the window resize to finish");
    return false;
  }
  int size[2];
  const bool switched = Mixar_window_gpu_context_push(CTX_wm_manager(C), win);
  uint8_t *pixels = WM_window_pixels_read_from_offscreen(C, win, size);
  if (switched) { Mixar_window_gpu_context_pop(CTX_wm_manager(C)); }
  if (!pixels) {
    BKE_report(reports, RPT_ERROR, "Unable to read window frame");
    return false;
  }
  ImBuf *buffer = IMB_allocImBuf(size[0], size[1], ImBufFlags::Zero);
  buffer->color_mode = ImColorMode::RGB;
  buffer->assign_byte_data(pixels);
  if (width > 0 && height > 0) {
    x = std::clamp(x, 0, size[0] - 1);
    y = std::clamp(y, 0, size[1] - 1);
    IMB_crop(buffer, int2(x, y),
             int2(std::min(width, size[0] - x), std::min(height, size[1] - y)));
  }
  ImageFormatData format;
  BKE_image_format_init(&format);
  format.imtype = R_IMF_IMTYPE_PNG;
  const bool saved = BKE_imbuf_write(buffer, filepath, &format);
  IMB_freeImBuf(buffer);
  return saved;
}

static bool rna_Window_mixar_qa_capture_frame(wmWindow *win, bContext *C,
    ReportList *reports, const char *filepath, int x, int y, int width, int height)
{
  if (!(G.f & G_FLAG_EVENT_SIMULATE)) {
    BKE_report(reports, RPT_ERROR, "QA frame capture requires --enable-event-simulate");
    return false;
  }
  return rna_ui_capture(win, C, reports, filepath, x, y, width, height);
}

static bool rna_ui_capture_enabled(wmWindow *win, bContext *C, ReportList *reports,
    const char *filepath, int x, int y, int width, int height)
{
  if (!Mixar_ui_control_enabled()) {
    BKE_report(reports, RPT_ERROR, "Mixar UI control is disabled");
    return false;
  }
  return rna_ui_capture(win, C, reports, filepath, x, y, width, height);
}
#else
static void RNA_def_mixar_ui_control(BlenderRNA *brna, StructRNA *window)
{
  StructRNA *wm = brna->structs_map.lookup_default("WindowManager", nullptr);
  if (!wm) { return; }
  FunctionRNA *func = RNA_def_function(wm, "mixar_ui_enable", "rna_ui_enable");
  RNA_def_boolean(func, "enabled", false, "Enabled", "Enable local UI control");
  func = RNA_def_function(wm, "mixar_ui_begin", "rna_ui_begin");
  RNA_def_string(func, "owner", nullptr, 128, "Owner", "Controller lease token");
  RNA_def_function_return(func, RNA_def_boolean(func, "accepted", false, "", ""));
  func = RNA_def_function(wm, "mixar_ui_end", "rna_ui_end");
  RNA_def_string(func, "owner", nullptr, 128, "Owner", "Controller lease token");
  func = RNA_def_function(wm, "mixar_ui_generation", "rna_ui_generation");
  RNA_def_function_return(func, RNA_def_int(func, "generation", 0, 0, INT_MAX, "", "", 0, INT_MAX));
  func = RNA_def_function(wm, "mixar_ui_pending", "rna_ui_pending");
  RNA_def_function_return(func, RNA_def_int(func, "count", 0, 0, INT_MAX, "", "", 0, INT_MAX));

  func = RNA_def_function(window, "mixar_ui_event", "rna_ui_event");
  RNA_def_function_flag(func, FUNC_USE_CONTEXT | FUNC_USE_REPORTS);
  RNA_def_string(func, "owner", nullptr, 128, "Owner", "Controller lease token");
  RNA_def_enum(func, "type", rna_enum_event_type_items, 0, "Type", "");
  RNA_def_enum(func, "value", rna_enum_event_value_items, 0, "Value", "");
  RNA_def_string(func, "text", nullptr, 8, "Text", "Single UTF-8 character");
  for (const char *name : {"x", "y"}) {
    RNA_def_int(func, name, 0, INT_MIN, INT_MAX, "", "", INT_MIN, INT_MAX);
  }
  for (const char *name : {"shift", "ctrl", "alt", "oskey"}) {
    RNA_def_boolean(func, name, false, "", "");
  }
  RNA_def_function_return(func, RNA_def_boolean(func, "queued", false, "", ""));

  func = RNA_def_function(window, "mixar_ui_modal_count", "rna_ui_modal_count");
  RNA_def_function_return(func, RNA_def_int(func, "count", 0, 0, INT_MAX, "", "", 0, INT_MAX));

  func = RNA_def_function(window, "mixar_ui_capture", "rna_ui_capture_enabled");
  RNA_def_function_flag(func, FUNC_USE_CONTEXT | FUNC_USE_REPORTS);
  RNA_def_string_file_path(func, "filepath", nullptr, 1024, "", "PNG path");
  for (const char *name : {"x", "y", "width", "height"}) {
    RNA_def_int(func, name, 0, 0, INT_MAX, "", "", 0, INT_MAX);
  }
  RNA_def_function_return(func, RNA_def_boolean(func, "saved", false, "", ""));
}
#endif
}  // namespace blender
