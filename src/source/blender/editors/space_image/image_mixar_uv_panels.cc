/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spimage
 *
 * Mixar UV panels (Redo, Transform, Unwrap) for IMAGE_EDITOR sidebar.
 */

#include <cmath>
#include <cstring>

#include "MEM_guardedalloc.h"

#include "DNA_object_types.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_view3d_types.h"
#include "DNA_workspace_types.h"

#include "BLI_listbase.h"

#include "BLI_math_vector.h"
#include "BLI_string_utf8.h"
#include "BLI_utildefines.h"

#include "BLT_translation.hh"

#include "BKE_context.hh"
#include "BKE_editmesh.hh"
#include "BKE_layer.hh"
#include "BKE_screen.hh"

#include "ED_image.hh"
#include "ED_undo.hh"
#include "ED_uvedit.hh"

#include "WM_api.hh"
#include "WM_toolsystem.hh"

#include "UI_interface.hh"
#include "UI_interface_layout.hh"
#include "UI_resources.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"
#include "RNA_enum_types.hh"
#include "RNA_prototypes.hh"

#include "image_mixar_uv_panels.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

using blender::Span;
using blender::Vector;

/* Mixar 5.2 port: RNA struct handles come from the generated RNA_prototypes.hh
 * (`extern StructRNA *RNA_X` pointers in `namespace blender`). Hand-rolled
 * `extern StructRNA RNA_X` object declarations compile per-TU and only fail at
 * final link. */

/* Forward declarations for helpers in image_mixar_uv_helpers.cc */
int mixar_uvedit_center(Scene *scene, const Span<Object *> objects, float center[2]);
bool mixar_uvedit_bounds(Scene *scene,
                         const Span<Object *> objects,
                         float min_uv[2],
                         float max_uv[2]);

/* -------------------------------------------------------------------- */
/** \name Redo Panel
 * \{ */

static void mixar_uv_redo_cb(bContext *C, void *arg_op, int /*arg_unused*/)
{
  wmOperator *op = static_cast<wmOperator *>(arg_op);
  if (op == nullptr) {
    return;
  }

  /* Switch to WINDOW region for operator repeat */
  ARegion *window_region = mixar_uv_find_window_region(C);
  if (window_region == nullptr) {
    return;
  }

  ARegion *region_prev = CTX_wm_region(C);
  CTX_wm_region_set(C, window_region);

  ED_undo_operator_repeat(C, op);

  CTX_wm_region_set(C, region_prev);
}

static bool mixar_uv_redo_panel_poll(const bContext *C, PanelType * /*pt*/)
{
  /* Only show in MIXAR_UV mode */
  SpaceImage *sima = CTX_wm_space_image(C);
  if (!sima || sima->mode != SI_MODE_MIXAR_UV) {
    return false;
  }

  /* Check if Transform panel is selected */
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm != nullptr) {
    PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
    PropertyRNA *prop = RNA_struct_find_property(&wm_ptr, "mixar_uv_ui");
    if (prop != nullptr) {
      PointerRNA mixar_uv_ui = RNA_pointer_get(&wm_ptr, "mixar_uv_ui");
      if (mixar_uv_ui.data != nullptr) {
        int active_panel = RNA_enum_get(&mixar_uv_ui, "active_panel");
        if (active_panel != 1) { /* 1 = TRANSFORM */
          return false;
        }
      }
    }
  }

  wmOperator *op = WM_operator_last_redo(C);
  if (op == nullptr) {
    return false;
  }

  /* Exclude operators with dedicated real-time UI */
  if (STREQ(op->type->idname, "UV_OT_arrange_islands") ||
      STREQ(op->type->idname, "UV_OT_move_on_axis") ||
      STREQ(op->type->idname, "UV_OT_unwrap")) {
    return false;
  }

  if (!WM_operator_repeat_check(C, op)) {
    return false;
  }

  if (!WM_operator_ui_poll(op->type, op->ptr)) {
    return false;
  }

  return true;
}

static void mixar_uv_redo_panel_draw_header(const bContext *C, Panel *panel)
{
  wmOperator *op = WM_operator_last_redo(C);
  if (op != nullptr) {
    const std::string opname = WM_operatortype_name(op->type, op->ptr);
    ui::panel_drawname_set(panel, opname);
  }
}

static void mixar_uv_redo_panel_draw(const bContext *C, Panel *panel)
{
  wmOperator *op = WM_operator_last_redo(C);
  if (op == nullptr) {
    return;
  }

  if (!WM_operator_check_ui_enabled(C, op->type->name)) {
    panel->layout->enabled_set(false);
  }

  ui::Block *block = panel->layout->block();
  ui::block_func_handle_set(block, mixar_uv_redo_cb, op);

  /* Switch region for property drawing */
  ARegion *window_region = mixar_uv_find_window_region(C);
  ARegion *region_prev = CTX_wm_region(C);

  if (window_region) {
    CTX_wm_region_set((bContext *)C, window_region);
  }

  ui::Layout *col = &panel->layout->column(false);

  if (WM_operator_repeat_check(C, op)) {
    ui::uiTemplateOperatorPropertyButs(C, col, op, ui::BUT_LABEL_ALIGN_NONE, 0);
  }

  CTX_wm_region_set((bContext *)C, region_prev);
}

void mixar_uv_redo_panel_register(ARegionType *art)
{
  PanelType *pt = MEM_new_zeroed<PanelType>("mixar_uv_redo_panel");

  STRNCPY_UTF8(pt->idname, "MIXAR_UV_PT_redo");
  STRNCPY_UTF8(pt->label, N_("Adjust Last Operation"));
  STRNCPY_UTF8(pt->translation_context, BLT_I18NCONTEXT_DEFAULT_BPYRNA);

  pt->draw_header = mixar_uv_redo_panel_draw_header;
  pt->draw = mixar_uv_redo_panel_draw;
  pt->poll = mixar_uv_redo_panel_poll;
  pt->space_type = SPACE_IMAGE;
  pt->region_type = RGN_TYPE_CHANNELS;
  pt->flag |= PANEL_TYPE_DEFAULT_CLOSED;

  BLI_addtail(&art->paneltypes, pt);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Transform Panel
 * \{ */

static bool mixar_uv_transform_panel_poll(const bContext *C, PanelType * /*pt*/)
{
  Object *obedit = CTX_data_edit_object(C);
  if (!ED_uvedit_test(obedit)) {
    return false;
  }

  SpaceImage *sima = CTX_wm_space_image(C);
  if (!sima || sima->mode != SI_MODE_MIXAR_UV) {
    return false;
  }

  /* Tool-bar selection takes priority over header selection in the
   * sidebar: whenever `builtin.transform` is the active workspace
   * tool, this panel shows regardless of which header tab is
   * selected. The header panel for that tab hides itself when its
   * `poll` sees a tool-bound panel is about to show — see
   * `base.panels.tool_panel_is_active`. */
  ScrArea *area = CTX_wm_area(C);
  bToolRef *tref = area->runtime.tool;
  return tref && STREQ(tref->idname, "builtin.transform");
}

static void mixar_uv_transform_panel_draw(const bContext *C, Panel *panel)
{
  /* Switch to WINDOW region for UV data access */
  ARegion *window_region = mixar_uv_find_window_region(C);
  if (window_region == nullptr) {
    return;
  }

  ARegion *region_prev = CTX_wm_region(C);
  CTX_wm_region_set((bContext *)C, window_region);

  SpaceImage *sima = CTX_wm_space_image(C);
  Scene *scene = CTX_data_scene(C);
  float center[2];
  int imx, imy, step = 1, digits = 3;

  /* Sync pivot from IMAGE_EDITOR space */
  mixar_uv_pivot_point = sima->around;

  Vector<Object *> objects = BKE_view_layer_array_from_objects_in_edit_mode_unique_data_with_uvs(
      *CTX_data_main(C), scene, CTX_data_view_layer(C), CTX_wm_view3d(C));

  ED_space_image_get_size(sima, &imx, &imy);

  /* Compute dynamic control width from CHANNELS sidebar so the live
   * absolute-positioned widgets fill the Selection-style box instead of
   * leaving an empty gutter on the right. */
  const int sidebar_width = region_prev ? region_prev->winx : 0;
  const int box_padding = UI_UNIT_X * 2;
  const int control_width = (sidebar_width > box_padding * 2 + UI_UNIT_X * 6)
                                ? (sidebar_width - box_padding * 2)
                                : (UI_UNIT_X * 12);

  /* ===== Merged Move/Pivot/Rotation/Scale sub-section =====
   *
   * One Selection-style box, no inner section headers — just four rows
   * each with an inline label on the left and its controls on the
   * right:
   *   1. `Move`            | X [v]   Y [v]
   *   2. `Pivot`           | dropdown
   *   3. `Rotation Angle`  | input
   *   4. `Scale`           | X [v]   Y [v]
   * The Move row dims when nothing is selected; the Scale row dims
   * when there are no bounds. Pivot stays interactive in both states. */
  {
    ui::Layout *xform_box = &panel->layout->box();
    ui::Layout *xform_col = &xform_box->column(false);

    const bool has_selection = mixar_uvedit_center(scene, objects, center);

    float range_xy[2][2] = {{-10.0f, 10.0f}, {-10.0f, 10.0f}};
    if (has_selection) {
      copy_v2_v2(mixar_uv_vertex_old_center, center);

      CLAMP_MAX(range_xy[0][0], mixar_uv_vertex_old_center[0]);
      CLAMP_MIN(range_xy[0][1], mixar_uv_vertex_old_center[0]);
      CLAMP_MAX(range_xy[1][0], mixar_uv_vertex_old_center[1]);
      CLAMP_MIN(range_xy[1][1], mixar_uv_vertex_old_center[1]);

      if (!(sima->flag & SI_COORDFLOATS)) {
        mixar_uv_vertex_old_center[0] *= imx;
        mixar_uv_vertex_old_center[1] *= imy;
        mul_v2_fl(range_xy[0], imx);
        mul_v2_fl(range_xy[1], imy);
      }
    }
    else {
      mixar_uv_vertex_old_center[0] = 0.0f;
      mixar_uv_vertex_old_center[1] = 0.0f;
      mixar_uv_vertex_old_angle = 0.0f;
    }

    if (sima->flag & SI_COORDFLOATS) {
      step = 1;
      digits = 3;
    }
    else {
      step = 100;
      digits = 2;
    }

    /* Compute bounds (size) for the Scale row. */
    float min_uv[2], max_uv[2];
    const bool has_bounds = mixar_uvedit_bounds(scene, objects, min_uv, max_uv);
    if (has_bounds) {
      mixar_uv_size_target[0] = max_uv[0] - min_uv[0];
      mixar_uv_size_target[1] = max_uv[1] - min_uv[1];
    }
    else {
      mixar_uv_size_target[0] = 0.0f;
      mixar_uv_size_target[1] = 0.0f;
    }

    /* Geometry shared by the Move / Scale rows (left label : right
     * content split at 40 / 60, then the right half is split into
     * X label + input | Y label + input). */
    const int row_label_w = int(control_width * 0.4f);
    const int content_w = control_width - row_label_w;
    /* Visual gutter between the X input and the Y label so the two
     * number fields read as separate pairs instead of touching. */
    const int xy_gap = int(UI_UNIT_X * 0.5f);
    const int half_content = (content_w - xy_gap) / 2;
    const int xy_label_w = int(UI_UNIT_X * 0.6f);
    const int xy_input_w = half_content - xy_label_w;

    /* ---- Row 1: Move | X | Y ---- */
    ui::Layout *move_wrapper = &xform_col->column(false);
    move_wrapper->active_set(has_selection);
    ui::Block *move_block = move_wrapper->block();
move_wrapper->absolute(false);
    ui::block_func_handle_set(move_block, do_mixar_uvedit_transform, nullptr);

    ui::Button *but;
    int y = -UI_UNIT_Y;
    ui::uiDefBut(move_block, ui::ButtonType::Label, IFACE_("Move"),
             0, y, row_label_w, UI_UNIT_Y, nullptr, 0.0f, 0.0f, "");
    ui::uiDefBut(move_block, ui::ButtonType::Label, IFACE_("X"),
             row_label_w, y, xy_label_w, UI_UNIT_Y,
             nullptr, 0.0f, 0.0f, "");
    but = ui::uiDefButV(move_block, ui::ButtonType::Num, "",
                     row_label_w + xy_label_w, y, xy_input_w, UI_UNIT_Y,
                     &mixar_uv_vertex_old_center[0], UNPACK2(range_xy[0]), "");
    ui::button_retval_set(but, B_MIXAR_UVEDIT_VERTEX);
    ui::button_number_step_size_set(but, step);
    ui::button_number_precision_set(but, digits);
    ui::uiDefBut(move_block, ui::ButtonType::Label, IFACE_("Y"),
             row_label_w + half_content + xy_gap, y,
             xy_label_w, UI_UNIT_Y, nullptr, 0.0f, 0.0f, "");
    but = ui::uiDefButV(move_block, ui::ButtonType::Num, "",
                     row_label_w + half_content + xy_gap + xy_label_w, y,
                     xy_input_w, UI_UNIT_Y,
                     &mixar_uv_vertex_old_center[1], UNPACK2(range_xy[1]), "");
    ui::button_retval_set(but, B_MIXAR_UVEDIT_VERTEX);
    ui::button_number_step_size_set(but, step);
    ui::button_number_precision_set(but, digits);

    /* ---- Row 2: Pivot | dropdown ----
     * Use an explicit 40/60 split (matching the Texel Density panel)
     * with a left-aligned `Pivot` label so the row lines up with Move /
     * Rotation Angle / Scale rather than right-aligning via
     * `use_property_split`. */
    xform_col->separator(0.5f);
    PointerRNA sima_ptr = RNA_pointer_create_discrete(
        nullptr, RNA_SpaceImageEditor, sima);
    ui::Layout *pivot_split = &xform_col->split(0.4f, false);
    pivot_split->label(IFACE_("Pivot"), ICON_NONE);
    pivot_split->prop(&sima_ptr, "pivot_point", UI_ITEM_NONE,
                       "", ICON_NONE);

    /* ---- Row 3: Rotation Angle | input ---- */
    xform_col->separator(0.5f);
    ui::Layout *angle_wrapper = &xform_col->column(false);
    angle_wrapper->active_set(has_selection);
    ui::Block *angle_block = angle_wrapper->block();
angle_wrapper->absolute(false);
    ui::block_func_handle_set(angle_block, do_mixar_uvedit_transform, nullptr);

    const int angle_input_w = control_width - row_label_w;
    ui::uiDefBut(angle_block, ui::ButtonType::Label, IFACE_("Rotation Angle"),
             0, -UI_UNIT_Y, row_label_w, UI_UNIT_Y,
             nullptr, 0.0f, 0.0f, "");
    ui::Button *angle_but = ui::uiDefButV(angle_block, ui::ButtonType::Num, "",
                                 row_label_w, -UI_UNIT_Y,
                                 angle_input_w, UI_UNIT_Y,
                                 &mixar_uv_vertex_old_angle, -360.0f, 360.0f,
                                 "Rotation angle in degrees");
    ui::button_retval_set(angle_but, B_MIXAR_UVEDIT_ROTATE);
    ui::button_number_step_size_set(angle_but, 1);
    ui::button_number_precision_set(angle_but, 3);

    /* ---- Row 4: Scale | X | Y ---- */
    xform_col->separator(0.5f);
    ui::Layout *scale_wrapper = &xform_col->column(false);
    scale_wrapper->active_set(has_bounds);
    ui::Block *scale_block = scale_wrapper->block();
scale_wrapper->absolute(false);
    ui::block_func_handle_set(scale_block, do_mixar_uvedit_transform, nullptr);

    y = -UI_UNIT_Y;
    ui::uiDefBut(scale_block, ui::ButtonType::Label, IFACE_("Scale"),
             0, y, row_label_w, UI_UNIT_Y, nullptr, 0.0f, 0.0f, "");
    ui::uiDefBut(scale_block, ui::ButtonType::Label, IFACE_("X"),
             row_label_w, y, xy_label_w, UI_UNIT_Y,
             nullptr, 0.0f, 0.0f, "");
    but = ui::uiDefButV(scale_block, ui::ButtonType::Num, "",
                     row_label_w + xy_label_w, y, xy_input_w, UI_UNIT_Y,
                     &mixar_uv_size_target[0], 0.0f, 10.0f, "Width in UV space");
    ui::button_retval_set(but, B_MIXAR_UVEDIT_SCALE);
    ui::button_number_step_size_set(but, 1);
    ui::button_number_precision_set(but, 3);
    ui::uiDefBut(scale_block, ui::ButtonType::Label, IFACE_("Y"),
             row_label_w + half_content + xy_gap, y,
             xy_label_w, UI_UNIT_Y, nullptr, 0.0f, 0.0f, "");
    but = ui::uiDefButV(scale_block, ui::ButtonType::Num, "",
                     row_label_w + half_content + xy_gap + xy_label_w, y,
                     xy_input_w, UI_UNIT_Y,
                     &mixar_uv_size_target[1], 0.0f, 10.0f, "Height in UV space");
    ui::button_retval_set(but, B_MIXAR_UVEDIT_SCALE);
    ui::button_number_step_size_set(but, 1);
    ui::button_number_precision_set(but, 3);
  }

  /* ===== Move on Axis sub-section ===== */
  {
    ui::Layout *axis_box = &panel->layout->box();
    ui::Layout *axis_col = &axis_box->column(false);
    axis_col->label(IFACE_("Move on Axis"), ICON_EMPTY_AXIS);
    axis_col->separator(0.5f);

    wmOperatorType *ot_uv = WM_operatortype_find("UV_OT_move_on_axis", false);
    if (ot_uv) {
      PointerRNA op_ptr;
      WM_operator_last_properties_ensure(ot_uv, &op_ptr);

      /* Type / Axis / Distance — render as left-aligned `[label][input]`
       * rows that match the Texel Density panel style (40/60 split) so
       * the labels line up with the Move / Pivot / Rotation Angle /
       * Scale rows above. The previous `use_property_split` version
       * right-aligned the labels, which broke visual consistency.
       *
       * The props are RNA-bound to the operator's last properties so
       * edits flow straight back into them. */
      auto axis_row = [&](const char *label, const char *prop_id) {
        ui::Layout *sp = &axis_col->split(0.4f, false);
        sp->label(IFACE_(label), ICON_NONE);
        sp->prop(&op_ptr, prop_id, UI_ITEM_NONE, "", ICON_NONE);
      };
      axis_row("Type", "type");
      axis_row("Axis", "axis");
      axis_row("Distance", "distance");

      axis_col->separator(1.0f);

      ui::Layout *row = &axis_col->row(false);
      row->scale_y_set(1.3f);
      ui::Block *apply_move_block = row->block();
row->absolute(false);
      ui::block_func_handle_set(apply_move_block, do_mixar_uvedit_transform, nullptr);
      ui::Button *apply_move_but = ui::uiDefBut(apply_move_block,
                                                ui::ButtonType::But,
                                                IFACE_("Apply Move"),
                                                0,
                                                0,
                                                control_width,
                                                UI_UNIT_Y * 1.3f,
                                                nullptr,
                                                0.0f,
                                                0.0f,
                                                "Apply move with current distance");
      ui::button_retval_set(apply_move_but, B_MIXAR_UVEDIT_MOVE_AXIS);
    }
  }

  /* ===== 2D Cursor sub-section ===== */
  {
    ui::Layout *cursor_box = &panel->layout->box();
    ui::Layout *cursor_col = &cursor_box->column(false);
    cursor_col->label(IFACE_("2D Cursor"), ICON_PIVOT_CURSOR);
    cursor_col->separator(0.5f);

    if (sima->flag & SI_COORDFLOATS) {
      copy_v2_v2(mixar_uv_cursor_edit, sima->cursor);
    }
    else {
      mixar_uv_cursor_edit[0] = sima->cursor[0] * float(imx);
      mixar_uv_cursor_edit[1] = sima->cursor[1] * float(imy);
    }

    ui::Block *cursor_block = cursor_col->block();
cursor_col->absolute(false);
    ui::block_func_handle_set(cursor_block, do_mixar_uvedit_transform, nullptr);

    /* X and Y on one row with external labels. A horizontal gutter
     * separates the X input from the Y label so the two number fields
     * read as distinct pairs instead of one continuous strip. */
    const int xy_gap = int(UI_UNIT_X * 0.8f);
    const int half_w = (control_width - xy_gap) / 2;
    const int label_w = int(UI_UNIT_X * 0.8f);
    const int input_w = half_w - label_w;

    ui::Button *but;
    int y = -UI_UNIT_Y;
    ui::uiDefBut(cursor_block, ui::ButtonType::Label, IFACE_("X"),
             0, y, label_w, UI_UNIT_Y, nullptr, 0.0f, 0.0f, "");
    but = ui::uiDefButV(cursor_block, ui::ButtonType::Num, "",
                     label_w, y, input_w, UI_UNIT_Y,
                     &mixar_uv_cursor_edit[0], -FLT_MAX, FLT_MAX, "Cursor X position");
    ui::button_retval_set(but, B_MIXAR_UVEDIT_CURSOR);
    ui::button_number_step_size_set(but, step);
    ui::button_number_precision_set(but, digits);
    ui::uiDefBut(cursor_block, ui::ButtonType::Label, IFACE_("Y"),
             half_w + xy_gap, y, label_w, UI_UNIT_Y, nullptr, 0.0f, 0.0f, "");
    but = ui::uiDefButV(cursor_block, ui::ButtonType::Num, "",
                     half_w + xy_gap + label_w, y, input_w, UI_UNIT_Y,
                     &mixar_uv_cursor_edit[1], -FLT_MAX, FLT_MAX, "Cursor Y position");
    ui::button_retval_set(but, B_MIXAR_UVEDIT_CURSOR);
    ui::button_number_step_size_set(but, step);
    ui::button_number_precision_set(but, digits);
  }

  /* ===== Mirror sub-section ===== */
  {
    ui::Layout *mirror_box = &panel->layout->box();
    ui::Layout *mirror_col = &mirror_box->column(false);
    mirror_col->label(IFACE_("Mirror"), ICON_MOD_MIRROR);
    mirror_col->separator(0.5f);

    ui::Layout *row = &mirror_col->row(true);
    row->scale_y_set(1.3f);
    PointerRNA op_props_x = row->op("MIXAR_OT_mirror", IFACE_("X Axis"), ICON_NONE);
    RNA_enum_set_identifier((bContext *)C, &op_props_x, "axis", "X");
    PointerRNA op_props_y = row->op("MIXAR_OT_mirror", IFACE_("Y Axis"), ICON_NONE);
    RNA_enum_set_identifier((bContext *)C, &op_props_y, "axis", "Y");
  }

  /* Proportional Editing UI moved to the IMAGE_HT_header (next to the
   * sticky selection icons), matching Blender's stock UV header. */

  /* Snapping / Round to Pixels / Align / Align Rotation moved to the
   * Python Tool panel — see uv_editor/ui/uv_tool/panels.py
   * (MIXAR_UV_PT_uv_tool). */

  /* Restore original region */
  CTX_wm_region_set((bContext *)C, region_prev);
}

void mixar_uv_transform_panel_register(ARegionType *art)
{
  PanelType *pt = MEM_new_zeroed<PanelType>("mixar_uv_transform_panel");

  STRNCPY_UTF8(pt->idname, "MIXAR_UV_PT_transform");
  STRNCPY_UTF8(pt->label, N_("Transform"));
  STRNCPY_UTF8(pt->translation_context, BLT_I18NCONTEXT_DEFAULT_BPYRNA);

  pt->draw = mixar_uv_transform_panel_draw;
  pt->poll = mixar_uv_transform_panel_poll;
  pt->space_type = SPACE_IMAGE;
  pt->region_type = RGN_TYPE_CHANNELS;
  /* Transform is a regular tool-based panel (not one of the
   * always-priority brush panels). Sort in the bottom band so any
   * header-tab panel (bl_order=50) sits above us; UV Sculpt Tools
   * and Annotate (bl_order=-10) stay on top of everything. */
  pt->order = 100;

  BLI_addtail(&art->paneltypes, pt);
}

/** \} */
}  // namespace blender
