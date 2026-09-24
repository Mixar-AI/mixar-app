/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup RNA
 *
 * Mixar-specific extensions to the WindowManager RNA.
 *
 * Adds the ``Window.global_areas`` collection so Python can
 * iterate global areas (topbar, statusbar). Upstream Blender
 * intentionally hides these because they're "system" areas not
 * meant to be addressed by addons, but Mixar's onboarding tour
 * needs to tag the topbar's regions for redraw from a Python
 * timer so the highlight border appears on step entry instead of
 * on cursor hover.
 *
 * Structure mirrors upstream rna_*.cc files: helper functions
 * inside ``#ifdef RNA_RUNTIME`` (compiled into Blender runtime via
 * the generated gen files including this .cc), ``RNA_def_*``
 * inside the ``#else`` branch (compiled into the makesrna binary
 * which generates the runtime code).
 *
 * This file briefly also exposed a **report channel** on
 * ``WindowManager`` (``mixar_last_report`` / ``_type`` /
 * ``mixar_report_count``) for the agent island to paint inline; it was
 * removed because Blender's global report list carries unrelated app
 * activity — the agent's own sandboxed script execution above all — so
 * pane messages now come from a dedicated channel that only the pane's
 * own action writes (``agent_bubble/ui/properties/pane_message_props.py``).
 *
 * The table entry for this file is registered in Mixar's overlay
 * of ``makesrna.cc`` (right after ``rna_wm.cc``). That same overlay
 * includes the runtime helpers only in the generated ``rna_wm_gen.cc``
 * (not the empty ``rna_wm_mixar_gen.cc``) so the functions below are
 * visible to the auto-generated property wrappers for Window
 * (which are emitted into rna_wm_gen.cc because Window itself was
 * registered in rna_wm.cc).
 */

#include <climits>

#include "RNA_define.hh"

#include "rna_internal.hh"

#include "DNA_screen_types.h"
#include "DNA_windowmanager_types.h"

#include "BLI_listbase.h"

#ifdef RNA_RUNTIME
#  include <algorithm>
#  include <cstring>
#  include <string>
#  include <sstream>
#  include "BLI_serialize.hh"

#  include "BKE_global.hh"
#  include "BKE_image.hh"
#  include "BKE_image_format.hh"
#  include "BKE_report.hh"
#  include "DNA_scene_types.h"
#  include "IMB_imbuf.hh"
#  include "IMB_imbuf_types.hh"
#  include "WM_api.hh"

#  include "../../editors/interface/interface_qa_inspect.hh"
#else
#  include "rna_internal_types.hh"
#endif

/* Mixar 5.2 port: namespace wrap. Every include stays ABOVE this line: the
 * generated ``rna_*_gen.cc`` files include this .cc at global scope, and a
 * header pulled in after the wrap opens would land in ``blender::blender``. */
namespace blender {

#ifdef RNA_RUNTIME

static void rna_Window_global_areas_begin(CollectionPropertyIterator *iter, PointerRNA *ptr)
{
  wmWindow *win = (wmWindow *)ptr->data;
  rna_iterator_listbase_begin(iter, ptr, &win->global_areas.areabase, nullptr);
}

/* QA widget-tree dump (see interface_qa_inspect.cc). RNA string reads call
 * ``length`` then ``get`` back-to-back on the same thread, so the length
 * callback serializes into this cache and ``get`` copies + consumes it —
 * every Python read returns a freshly serialized dump, and ``get`` never
 * re-serializes into a buffer ``length`` already sized. */
static std::string g_mixar_qa_ui_dump_cache;

static int rna_WindowManager_mixar_qa_ui_dump_length(PointerRNA *ptr)
{
  const wmWindowManager *wm = (const wmWindowManager *)ptr->data;
  g_mixar_qa_ui_dump_cache = Mixar_ui_qa_inspect_json(wm);
  return int(g_mixar_qa_ui_dump_cache.size());
}

static void rna_WindowManager_mixar_qa_ui_dump_get(PointerRNA * /*ptr*/, char *value)
{
  /* ``value`` is sized by the ``length`` callback above, which is what
   * serializes the dump. Never re-serialize here: the UI may have changed
   * since, and a longer dump would overrun the caller's buffer. A read that
   * somehow skipped ``length`` gets an empty string, not a heap overflow. */
  memcpy(value, g_mixar_qa_ui_dump_cache.c_str(), g_mixar_qa_ui_dump_cache.size() + 1);
  g_mixar_qa_ui_dump_cache.clear();
  g_mixar_qa_ui_dump_cache.shrink_to_fit();
}

/* Defined in windowmanager/intern/wm_{event_system,window}.cc (Mixar overlay). */
void Mixar_qa_simulate_file_drop(bContext *C, wmWindow *win, int x, int y, Span<const char *> paths);
void Mixar_qa_simulate_file_drag(bContext *C, wmWindow *win, const char *filepath);
bool Mixar_window_resize_dispatch_active();

static bool rna_WindowManager_mixar_window_resizing_get(PointerRNA * /*ptr*/)
{
  return Mixar_window_resize_dispatch_active();
}

static void rna_Window_mixar_qa_drag_file(
    wmWindow *win, bContext *C, ReportList *reports, const char *filepath)
{
  if ((G.f & G_FLAG_EVENT_SIMULATE) == 0) {
    BKE_report(reports, RPT_ERROR, "Not running with '--enable-event-simulate' enabled");
    return;
  }
  Mixar_qa_simulate_file_drag(C, win, filepath);
}

static void rna_Window_mixar_qa_drop_file(
    wmWindow *win, bContext *C, ReportList *reports, const char *filepath, int x, int y,
    const char *filepaths_json)
{
  if ((G.f & G_FLAG_EVENT_SIMULATE) == 0) {
    BKE_report(reports, RPT_ERROR, "Not running with '--enable-event-simulate' enabled");
    return;
  }
  if (!filepaths_json || filepaths_json[0] == '\0') {
    if (filepath[0] != '\0') {
      Mixar_qa_simulate_file_drop(C, win, x, y, Span<const char *>(&filepath, 1));
    }
    return;
  }
  /* One real WM_DRAG_PATH payload for an OS multi-file drop, rather than
   * repeated single drops that cannot catch batch truncation/placement bugs. */
  std::istringstream stream(filepaths_json);
  io::serialize::JsonFormatter json;
  const std::unique_ptr<io::serialize::Value> value = json.deserialize(stream);
  const auto *array = value ? value->as_array_value() : nullptr;
  Vector<const char *> paths;
  if (array) {
    for (const auto &element : array->elements()) {
      const auto *path = element->as_string_value();
      if (!path || path->value().empty()) {
        BKE_report(reports, RPT_ERROR, "Drop paths must be nonempty strings");
        return;
      }
      paths.append(path->value().c_str());
    }
  }
  if (paths.is_empty()) {
    BKE_report(reports, RPT_ERROR, "Drop paths must be a nonempty JSON array");
    return;
  }
  Mixar_qa_simulate_file_drop(C, win, x, y, paths);
}

/* Mixar onboarding tour: a real top-bar menu opened under its own button
 * (editors/interface/mixar/tour_menu.cc). Public popup API, no synthesized input. */
bool Mixar_tour_menu_open(bContext *C, wmWindow *win, const char *menu_idname);
bool Mixar_tour_menu_close(wmWindow *win);
bool Mixar_tour_menu_is_open(wmWindow *win);

static bool rna_Window_mixar_tour_menu_open(wmWindow *win, bContext *C, const char *menu)
{
  return Mixar_tour_menu_open(C, win, menu);
}

static bool rna_Window_mixar_tour_menu_close(wmWindow *win)
{
  return Mixar_tour_menu_close(win);
}

static bool rna_Window_mixar_tour_menu_is_open(wmWindow *win)
{
  return Mixar_tour_menu_is_open(win);
}

/* Mixar: live GHOST client bounds (wm_draw.cc); wmWindow::posx/posy can be stale. */
bool Mixar_window_live_client_rect(const wmWindow *win, int r_rect[4]);

bool Mixar_window_content_rect_in(const wmWindow *win, const wmWindow *host, int r_rect[4]);

static void rna_Window_mixar_content_rect_in(wmWindow *win, wmWindow *host, int r_rect[4])
{
  if (!Mixar_window_content_rect_in(win, host, r_rect)) {
    r_rect[0] = r_rect[1] = r_rect[2] = r_rect[3] = 0;
  }
}

static void rna_Window_mixar_live_client_rect(wmWindow *win, int r_rect[4])
{
  if (!Mixar_window_live_client_rect(win, r_rect)) {
    r_rect[0] = r_rect[1] = r_rect[2] = r_rect[3] = 0;
  }
}

/** Observe cached UI frames. SCREEN_OT_screenshot deliberately calls
 * WM_redraw_windows to clear menus, which destroys the hover being measured. */
static bool rna_Window_mixar_qa_capture_frame(wmWindow *win,
                                              bContext *C,
                                              ReportList *reports,
                                              const char *filepath,
                                              int x,
                                              int y,
                                              int width,
                                              int height)
{
  if ((G.f & G_FLAG_EVENT_SIMULATE) == 0) {
    BKE_report(reports, RPT_ERROR, "QA frame capture requires --enable-event-simulate");
    return false;
  }
  int size[2];
  /* Front-buffer reads can rotate through stale swap-chain images. Recompose
   * cached region buffers without WM_redraw_windows or layout/event updates. */
  uint8_t *pixels = WM_window_pixels_read_from_offscreen(C, win, size);
  if (!pixels) {
    BKE_report(reports, RPT_ERROR, "Unable to read QA window frame");
    return false;
  }
  ImBuf *buffer = IMB_allocImBuf(size[0], size[1], ImBufFlags::Zero);
  buffer->color_mode = ImColorMode::RGB;
  buffer->assign_byte_data(pixels);
  if (width > 0 && height > 0) {
    x = std::clamp(x, 0, size[0] - 1);
    y = std::clamp(y, 0, size[1] - 1);
    IMB_crop(
        buffer, int2(x, y), int2(std::min(width, size[0] - x), std::min(height, size[1] - y)));
  }
  ImageFormatData format;
  BKE_image_format_init(&format);
  format.imtype = R_IMF_IMTYPE_PNG;
  const bool saved = BKE_imbuf_write(buffer, filepath, &format);
  IMB_freeImBuf(buffer);
  if (!saved) {
    BKE_report(reports, RPT_ERROR, "Unable to save QA window frame");
  }
  return saved;
}

#else /* RNA_RUNTIME */

void RNA_def_wm_mixar(BlenderRNA *brna)
{
  /* This file is part of the ``makesrna`` code generator, not the
   * runtime Blender binary, so ``RNA_struct_find`` (which queries
   * the runtime registry) isn't available here. Look up the
   * Window struct directly in ``brna->structs_map`` — the same
   * map used internally by the RNA define system (a
   * blender::Map<StringRef, StructRNA *> since 5.2). */
  if (brna == nullptr) {
    return;
  }
  StructRNA *srna = brna->structs_map.lookup_default("Window", nullptr);
  if (srna == nullptr) {
    /* Window struct must already be registered; runs after RNA_def_wm. */
    return;
  }

  PropertyRNA *prop = RNA_def_property(srna, "global_areas", PROP_COLLECTION, PROP_NONE);
  RNA_def_property_collection_funcs(prop,
                                    "rna_Window_global_areas_begin",
                                    "rna_iterator_listbase_next",
                                    "rna_iterator_listbase_end",
                                    "rna_iterator_listbase_get",
                                    nullptr,
                                    nullptr,
                                    nullptr,
                                    nullptr);
  RNA_def_property_struct_type(prop, "Area");
  RNA_def_property_clear_flag(prop, PROP_EDITABLE);
  RNA_def_property_ui_text(prop,
                           "Global Areas",
                           "Window-global areas (topbar, statusbar). Mixar extension — "
                           "exposed so onboarding can address the topbar for redraw.");

  /* QA harness: simulated OS file drop at a window coordinate — the one input
   * class ``event_simulate`` cannot express. */
  {
    FunctionRNA *func = RNA_def_function(
        srna, "mixar_qa_drag_file", "rna_Window_mixar_qa_drag_file");
    RNA_def_function_flag(func, FUNC_USE_CONTEXT | FUNC_USE_REPORTS);
    RNA_def_function_ui_description(
        func, "Preview a file entering the window without dropping (QA harness)");
    PropertyRNA *parm = RNA_def_string_file_path(
        func, "filepath", nullptr, 1024, "", "File being dragged");
    RNA_def_parameter_flags(parm, PropertyFlag(0), PARM_REQUIRED);
  }
  {
    FunctionRNA *func = RNA_def_function(
        srna, "mixar_qa_drop_file", "rna_Window_mixar_qa_drop_file");
    RNA_def_function_flag(func, FUNC_USE_CONTEXT | FUNC_USE_REPORTS);
    RNA_def_function_ui_description(
        func,
        "Simulate an OS file drop onto this window (QA harness; requires "
        "--enable-event-simulate)");
    PropertyRNA *parm = RNA_def_string_file_path(
        func, "filepath", nullptr, 1024, "", "File to drop");
    RNA_def_parameter_flags(parm, PropertyFlag(0), PARM_REQUIRED);
    parm = RNA_def_int(func, "x", 0, INT_MIN, INT_MAX, "", "", INT_MIN, INT_MAX);
    RNA_def_parameter_flags(parm, PropertyFlag(0), PARM_REQUIRED);
    parm = RNA_def_int(func, "y", 0, INT_MIN, INT_MAX, "", "", INT_MIN, INT_MAX);
    RNA_def_parameter_flags(parm, PropertyFlag(0), PARM_REQUIRED);
    RNA_def_string(func, "filepaths_json", nullptr, 0, "", "Optional JSON array of paths for one batch drop");
  }

  /* QA harness: JSON dump of every live widget across all windows (rects in
   * window pixels, ready for ``Window.event_simulate``). WindowManager was
   * also registered in rna_wm.cc, so its generated wrappers land in
   * rna_wm_gen.cc where the helpers above are visible via the same include
   * injection that serves ``Window.global_areas``. */
  {
    FunctionRNA *func = RNA_def_function(
        srna, "mixar_qa_capture_frame", "rna_Window_mixar_qa_capture_frame");
    RNA_def_function_flag(func, FUNC_USE_CONTEXT | FUNC_USE_REPORTS);
    RNA_def_function_ui_description(
        func,
        "Save a cached UI frame without clearing hover or menus (QA event-simulation mode only)");
    PropertyRNA *parm = RNA_def_string_file_path(func, "filepath", nullptr, 1024, "", "PNG path");
    RNA_def_parameter_flags(parm, PropertyFlag(0), PARM_REQUIRED);
    for (const char *name : {"x", "y", "width", "height"}) {
      RNA_def_int(func, name, 0, 0, INT_MAX, "", "Optional crop in window pixels", 0, INT_MAX);
    }
    parm = RNA_def_boolean(func, "success", false, "", "Frame saved");
    RNA_def_function_return(func, parm);
  }
  /* Live client bounds straight from GHOST — screen coordinates in points,
   * top-left origin (l, t, r, b) — for cross-window overlay geometry. */
  {
    FunctionRNA *func = RNA_def_function(
        srna, "mixar_live_client_rect", "rna_Window_mixar_live_client_rect");
    RNA_def_function_ui_description(
        func, "Current client bounds from the windowing system: (left, top, right, bottom) in "
              "screen points with a top-left origin; zeros when the window has no native window");
    PropertyRNA *parm = RNA_def_int_array(func, "rect", 4, nullptr, INT_MIN, INT_MAX, "Rect",
                                          "left, top, right, bottom", INT_MIN, INT_MAX);
    RNA_def_function_output(func, parm);
  }
  /* Onboarding tour: open / close a real top-bar menu under its button. */
  {
    FunctionRNA *func = RNA_def_function(srna, "mixar_tour_menu_open",
                                         "rna_Window_mixar_tour_menu_open");
    RNA_def_function_flag(func, FUNC_USE_CONTEXT);
    RNA_def_function_ui_description(
        func, "Onboarding tour: open a menu under its own pulldown button in this window, "
              "as a click would; False when the button is not on screen or it is already open");
    PropertyRNA *parm = RNA_def_string(func, "menu", nullptr, 0, "Menu", "Menu type idname");
    RNA_def_parameter_flags(parm, PropertyFlag(0), PARM_REQUIRED);
    parm = RNA_def_boolean(func, "opened", false, "", "");
    RNA_def_function_return(func, parm);

    func = RNA_def_function(srna, "mixar_tour_menu_close", "rna_Window_mixar_tour_menu_close");
    RNA_def_function_ui_description(func, "Onboarding tour: close the menu it opened");
    parm = RNA_def_boolean(func, "closed", false, "", "");
    RNA_def_function_return(func, parm);

    func = RNA_def_function(srna, "mixar_tour_menu_is_open",
                            "rna_Window_mixar_tour_menu_is_open");
    RNA_def_function_ui_description(func, "Onboarding tour: the menu it opened is still up");
    parm = RNA_def_boolean(func, "open", false, "", "");
    RNA_def_function_return(func, parm);
  }
  /* This window's client rect inside another window's client coordinates
   * (points, bottom-left origin) — exact across window styles. */
  {
    FunctionRNA *func = RNA_def_function(
        srna, "mixar_content_rect_in", "rna_Window_mixar_content_rect_in");
    RNA_def_function_ui_description(
        func, "This window's client rect in another window's client coordinates: "
              "(x, y, width, height) in points, bottom-left origin; zeros when unavailable");
    PropertyRNA *parm = RNA_def_pointer(func, "host", "Window", "", "The reference window");
    RNA_def_parameter_flags(parm, PROP_NEVER_NULL, PARM_REQUIRED);
    parm = RNA_def_int_array(func, "rect", 4, nullptr, INT_MIN, INT_MAX, "Rect",
                             "x, y, width, height", INT_MIN, INT_MAX);
    RNA_def_function_output(func, parm);
  }
  StructRNA *srna_wm = brna->structs_map.lookup_default("WindowManager", nullptr);
  if (srna_wm != nullptr) {
    prop = RNA_def_property(srna_wm, "mixar_qa_ui_dump", PROP_STRING, PROP_NONE);
    RNA_def_property_string_funcs(prop,
                                  "rna_WindowManager_mixar_qa_ui_dump_get",
                                  "rna_WindowManager_mixar_qa_ui_dump_length",
                                  nullptr);
    RNA_def_property_clear_flag(prop, PROP_EDITABLE);
    RNA_def_property_ui_text(
        prop,
        "QA UI Dump",
        "JSON snapshot of all live UI widgets (labels, operators, properties, "
        "window-space rects, state) for the Mixar QA harness");

    /* Timers and modal handlers also run from inside the OS resize callback
     * (see wm_window.cc). A viewport render there crashes macOS. */
    prop = RNA_def_property(srna_wm, "mixar_window_resizing", PROP_BOOLEAN, PROP_NONE);
    RNA_def_property_boolean_funcs(prop, "rna_WindowManager_mixar_window_resizing_get", nullptr);
    RNA_def_property_clear_flag(prop, PROP_EDITABLE);
    RNA_def_property_ui_text(
        prop,
        "Window Resizing",
        "Handlers are running from inside an OS window resize. Defer viewport "
        "renders (render.opengl) until this is False");
  }
}

#endif /* RNA_RUNTIME */

}  // namespace blender
