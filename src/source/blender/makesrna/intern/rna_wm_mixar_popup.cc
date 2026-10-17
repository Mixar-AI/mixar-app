/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/* Included by rna_wm_mixar.cc in makesrna and generated runtime wrappers (the
 * same split as rna_wm_ui_control.cc). Mixar pop-up RNA:
 *  - `Window.mixar_popup_block_open()`: a menu/popover/dialog owns the
 *    window's events (editors/interface/mixar/popup_query.cc).
 *  - `WindowManager.mixar_invoke_modal_dialog(operator, width)`: a centred
 *    props dialog that hides the Agent island and pill while open, hosted in
 *    the main window when invoked from the island (wm_operators.cc). */

namespace blender {
#ifdef RNA_RUNTIME

bool Mixar_window_popup_block_open(wmWindow *win);
wmOperatorStatus Mixar_operator_modal_dialog_popup(bContext *C,
                                                   wmOperator *op,
                                                   int width,
                                                   bool sheet);

static bool rna_Window_mixar_popup_block_open(wmWindow *win)
{
  return Mixar_window_popup_block_open(win);
}

static int rna_WindowManager_mixar_invoke_modal_dialog(bContext *C,
                                                       wmOperator *op,
                                                       int width,
                                                       bool sheet)
{
  return Mixar_operator_modal_dialog_popup(C, op, width, sheet);
}

#else

static void RNA_def_mixar_popup_query(BlenderRNA *brna, StructRNA *window)
{
  FunctionRNA *func = RNA_def_function(
      window, "mixar_popup_block_open", "rna_Window_mixar_popup_block_open");
  RNA_def_function_ui_description(
      func,
      "A menu, popover, search menu or dialog is open in this window; its modal "
      "handler owns every event until it closes");
  PropertyRNA *parm = RNA_def_boolean(func, "open", false, "", "");
  RNA_def_function_return(func, parm);

  StructRNA *wm = brna->structs_map.lookup_default("WindowManager", nullptr);
  if (wm == nullptr) {
    return;
  }
  /* Mirrors `invoke_props_dialog` (rna_wm_api.cc `rna_generic_op_invoke`). */
  func = RNA_def_function(
      wm, "mixar_invoke_modal_dialog", "rna_WindowManager_mixar_invoke_modal_dialog");
  RNA_def_function_ui_description(
      func,
      "Operator dialog like invoke_props_dialog, but centred, hosted in the main "
      "window when invoked from the Agent island, and hiding the island and pill "
      "until it closes");
  RNA_def_function_flag(func, FUNC_NO_SELF | FUNC_USE_CONTEXT);
  parm = RNA_def_pointer(func, "operator", "Operator", "", "Operator to call");
  RNA_def_parameter_flags(parm, PropertyFlag(0), PARM_REQUIRED);
  RNA_def_int(func, "width", 300, 0, INT_MAX, "", "Width of the popup", 0, INT_MAX);
  RNA_def_boolean(func,
                  "sheet",
                  false,
                  "Sheet",
                  "Open as a Mixar sheet: no title row, no padding, the framed card backdrop "
                  "(the operator's draw() calls layout.mixar_sheet_frame)");
  parm = RNA_def_enum_flag(
      func, "result", rna_enum_operator_return_items, OPERATOR_FINISHED, "result", "");
  RNA_def_function_return(func, parm);
}

#endif
}  // namespace blender
