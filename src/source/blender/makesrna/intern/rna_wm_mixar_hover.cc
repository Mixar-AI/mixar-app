/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/* Included by rna_wm_mixar.cc for makesrna and the generated runtime wrappers. */
namespace blender {
#ifdef RNA_RUNTIME

static void rna_WindowManager_mixar_bubble_hover_tick(bContext *C)
{
  /* UI-only heartbeat: keep native operator polling/context handling, but avoid
   * bpy.ops' pre/post view-layer evaluation. A timer must not flush a depsgraph
   * just to maintain island focus, window sizing and mascot scheduling. */
  WM_operator_name_call(
      C, "MIXAR_OT_bubble_hover_tick", wm::OpCallContext::ExecDefault, nullptr, nullptr);
}

#else

static void RNA_def_mixar_hover(BlenderRNA *brna)
{
  StructRNA *wm = brna->structs_map.lookup_default("WindowManager"_ustr, nullptr);
  if (wm == nullptr) {
    return;
  }
  FunctionRNA *func = RNA_def_function(
      wm, "mixar_bubble_hover_tick", "rna_WindowManager_mixar_bubble_hover_tick");
  RNA_def_function_flag(func, FUNC_NO_SELF | FUNC_USE_CONTEXT);
  RNA_def_function_ui_description(
      func, "Maintain island UI without evaluating scene dependencies");
}

#endif
}  // namespace blender
