/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 * \brief Scene Reconstruction tab for moodboard sidebar - reconstruct 3D scene from image
 */

#include "BKE_context.hh"

#include "BLI_string.h"

#include "DNA_scene_types.h"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"

#include "WM_api.hh"

#include "../mixie_moodboard_sidebar_constants.hh"
#include "../mixie_moodboard_sidebar_intern.hh"
#include "../mixie_moodboard_sidebar_types.hh"

namespace blender::ed::mixie::moodboard::sidebar {

/* ============================================================================
 * HELPER FUNCTION - Get tab properties
 * ============================================================================ */

static bool get_tab_properties(Scene *scene, PointerRNA &tab_ptr)
{
  if (!scene) {
    return false;
  }

  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *sidebar_prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_sidebar");
  if (!sidebar_prop) {
    return false;
  }

  PointerRNA sidebar_ptr = RNA_property_pointer_get(&scene_ptr, sidebar_prop);
  if (!sidebar_ptr.data) {
    return false;
  }

  PropertyRNA *tab_prop = RNA_struct_find_property(&sidebar_ptr, "tab_scene_recon");
  if (!tab_prop) {
    return false;
  }

  tab_ptr = RNA_property_pointer_get(&sidebar_ptr, tab_prop);
  if (!tab_ptr.data) {
    return false;
  }

  return true;
}

/* ============================================================================
 * INPUT IMAGE SECTION DRAWING
 * ============================================================================ */

/**
 * Draw the file picker image section (when toggle is OFF).
 * Shows filename if set, or a pick button.
 * Returns the total height used.
 */
static int draw_file_picker_image_section(ui::Block *block,
                                          PointerRNA *tab_ptr,
                                          int x,
                                          int y,
                                          int width)
{
  const int row_h = UI_UNIT_Y;
  const int spacing = ui_element_spacing();
  const int icon_w = dpi_scale(20);
  const int remove_btn_w = dpi_scale(24);

  int total_height = 0;
  int current_y = y;

  /* Check if we have an image path set */
  PropertyRNA *name_prop = RNA_struct_find_property(tab_ptr, "image_name");
  char image_name[256] = "";
  bool has_image = false;

  if (name_prop) {
    RNA_property_string_get(tab_ptr, name_prop, image_name);
    has_image = (image_name[0] != '\0');
  }

  if (has_image) {
    /* Show the image info with remove button */
    current_y -= row_h;
    total_height += row_h;

    /* Icon */
    ui::uiDefIconBut(block,
                 ui::ButtonType::Label,
                 0,
                 ICON_IMAGE_DATA,
                 x,
                 current_y,
                 icon_w,
                 row_h,
                 nullptr,
                 0.0f,
                 0.0f,
                 std::nullopt);

    /* Name label */
    const int info_width = width - icon_w - remove_btn_w - spacing;
    char name_label[280];
    BLI_snprintf(name_label, sizeof(name_label), "  %s", image_name);
    ui::uiDefBut(block,
             ui::ButtonType::Label,
             0,
             name_label,
             x + icon_w,
             current_y,
             info_width,
             row_h,
             nullptr,
             0.0f,
             0.0f,
             "Input image for scene reconstruction");

    /* Remove button */
    ui::uiDefIconButO(block,
                  ui::ButtonType::But,
                  "MIXIE_OT_scene_recon_remove_image",
                  blender::wm::OpCallContext::InvokeDefault,
                  ICON_X,
                  x + icon_w + info_width + spacing,
                  current_y,
                  remove_btn_w,
                  row_h,
                  "Remove input image");
  }
  else {
    /* Show pick button */
    current_y -= row_h;
    total_height += row_h;

    ui::uiDefIconTextButO(block,
                      ui::ButtonType::But,
                      "MIXIE_OT_scene_recon_pick_image",
                      blender::wm::OpCallContext::InvokeDefault,
                      ICON_ADD,
                      "Add Input Image",
                      x,
                      current_y,
                      width,
                      row_h,
                      "Select an image for scene reconstruction");
  }

  return total_height;
}

/**
 * Draw the selected moodboard image section (when toggle is ON).
 * Shows the first selected moodboard image (max 1).
 * Returns the total height used.
 */
static int draw_selected_moodboard_image(ui::Block *block,
                                         Scene *scene,
                                         int x,
                                         int y,
                                         int width)
{
  const int row_h = UI_UNIT_Y;
  const int icon_w = dpi_scale(20);

  int total_height = 0;
  int current_y = y;

  /* Get moodboard images collection */
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *mb_images_prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");
  if (!mb_images_prop) {
    return 0;
  }

  /* Find first selected image */
  bool found_selected = false;
  char image_name[256] = "";
  char image_resolution[64] = "";

  RNA_PROP_BEGIN (&scene_ptr, item_ptr, mb_images_prop) {
    PropertyRNA *selected_prop = RNA_struct_find_property(&item_ptr, "selected");
    if (selected_prop && RNA_property_boolean_get(&item_ptr, selected_prop)) {
      PropertyRNA *image_prop = RNA_struct_find_property(&item_ptr, "image");
      if (image_prop) {
        PointerRNA img_ptr = RNA_property_pointer_get(&item_ptr, image_prop);
        if (img_ptr.data) {
          found_selected = true;

          PropertyRNA *img_name_prop = RNA_struct_find_property(&img_ptr, "name");
          if (img_name_prop) {
            RNA_property_string_get(&img_ptr, img_name_prop, image_name);
          }

          PropertyRNA *size_prop = RNA_struct_find_property(&img_ptr, "size");
          if (size_prop) {
            int size[2] = {0, 0};
            RNA_property_int_get_array(&img_ptr, size_prop, size);
            if (size[0] > 0 && size[1] > 0) {
              BLI_snprintf(
                  image_resolution, sizeof(image_resolution), "%d x %d", size[0], size[1]);
            }
          }

          break;
        }
      }
    }
  }
  RNA_PROP_END;

  if (found_selected) {
    current_y -= row_h;
    total_height += row_h;

    ui::uiDefIconBut(block,
                 ui::ButtonType::Label,
                 0,
                 ICON_IMAGE_DATA,
                 x,
                 current_y,
                 icon_w,
                 row_h,
                 nullptr,
                 0.0f,
                 0.0f,
                 std::nullopt);

    char name_label[280];
    BLI_snprintf(name_label, sizeof(name_label), "  %s", image_name);
    ui::uiDefBut(block,
             ui::ButtonType::Label,
             0,
             name_label,
             x + icon_w,
             current_y,
             width - icon_w,
             row_h,
             nullptr,
             0.0f,
             0.0f,
             "Selected moodboard image");

    if (image_resolution[0] != '\0') {
      current_y -= row_h;
      total_height += row_h;

      char res_label[128];
      BLI_snprintf(res_label, sizeof(res_label), "    %s", image_resolution);
      ui::uiDefBut(block,
               ui::ButtonType::Label,
               0,
               res_label,
               x,
               current_y,
               width,
               row_h,
               nullptr,
               0.0f,
               0.0f,
               "Image resolution");
    }
  }
  else {
    current_y -= row_h;
    total_height += row_h;

    ui::uiDefBut(block,
             ui::ButtonType::Label,
             0,
             "Select an image in moodboard",
             x,
             current_y,
             width,
             row_h,
             nullptr,
             0.0f,
             0.0f,
             "Select one image in the moodboard to use for scene reconstruction");
  }

  return total_height;
}

/* ============================================================================
 * STATUS SECTION DRAWING
 * ============================================================================ */

/**
 * Draw the status section showing pipeline progress.
 * Handles both Phase 1 (GPU stages) and Phase 2 (3D model generation).
 * Returns the total height used.
 */
static int draw_status_section(ui::Block *block,
                               PointerRNA *tab_ptr,
                               int x,
                               int y,
                               int width)
{
  const int row_h = UI_UNIT_Y;
  const int spacing = ui_element_spacing();

  int total_height = 0;
  int current_y = y;

  /* Read status properties */
  char stage_name[256] = "";
  char stage_detail[256] = "";
  char status_text[64] = "";
  char phase[64] = "";
  float elapsed = 0.0f;
  int total_objects = 0;
  int completed_objects = 0;

  PropertyRNA *stage_name_prop = RNA_struct_find_property(tab_ptr, "stage_name");
  if (stage_name_prop) {
    RNA_property_string_get(tab_ptr, stage_name_prop, stage_name);
  }

  PropertyRNA *stage_detail_prop = RNA_struct_find_property(tab_ptr, "stage_detail");
  if (stage_detail_prop) {
    RNA_property_string_get(tab_ptr, stage_detail_prop, stage_detail);
  }

  PropertyRNA *status_prop = RNA_struct_find_property(tab_ptr, "status_text");
  if (status_prop) {
    RNA_property_string_get(tab_ptr, status_prop, status_text);
  }

  PropertyRNA *elapsed_prop = RNA_struct_find_property(tab_ptr, "elapsed_seconds");
  if (elapsed_prop) {
    elapsed = RNA_property_float_get(tab_ptr, elapsed_prop);
  }

  PropertyRNA *phase_prop = RNA_struct_find_property(tab_ptr, "phase");
  if (phase_prop) {
    RNA_property_string_get(tab_ptr, phase_prop, phase);
  }

  PropertyRNA *total_obj_prop = RNA_struct_find_property(tab_ptr, "total_objects");
  if (total_obj_prop) {
    total_objects = RNA_property_int_get(tab_ptr, total_obj_prop);
  }

  PropertyRNA *completed_obj_prop = RNA_struct_find_property(tab_ptr, "completed_objects");
  if (completed_obj_prop) {
    completed_objects = RNA_property_int_get(tab_ptr, completed_obj_prop);
  }

  /* Stage name */
  if (stage_name[0] != '\0') {
    current_y -= row_h;
    total_height += row_h;

    char stage_label[300];
    BLI_snprintf(stage_label, sizeof(stage_label), "Stage: %s", stage_name);
    ui::uiDefBut(block,
             ui::ButtonType::Label,
             0,
             stage_label,
             x,
             current_y,
             width,
             row_h,
             nullptr,
             0.0f,
             0.0f,
             "Current pipeline stage");
  }

  /* Stage detail */
  if (stage_detail[0] != '\0') {
    current_y -= row_h;
    total_height += row_h;

    ui::uiDefBut(block,
             ui::ButtonType::Label,
             0,
             stage_detail,
             x,
             current_y,
             width,
             row_h,
             nullptr,
             0.0f,
             0.0f,
             "Current operation detail");
  }

  /* Phase 2 object progress (when generating 3D models) */
  bool is_model_gen = (STREQ(phase, "model_generation") && total_objects > 0);
  if (is_model_gen) {
    current_y -= row_h;
    total_height += row_h;

    char progress_text[64];
    BLI_snprintf(progress_text, sizeof(progress_text), "Models: %d / %d completed", completed_objects, total_objects);
    ui::uiDefBut(block,
             ui::ButtonType::Label,
             0,
             progress_text,
             x,
             current_y,
             width,
             row_h,
             nullptr,
             0.0f,
             0.0f,
             "3D model generation progress");
  }

  /* Elapsed time */
  if (elapsed > 0.0f) {
    current_y -= row_h;
    total_height += row_h;

    int minutes = int(elapsed) / 60;
    int seconds = int(elapsed) % 60;
    char time_label[64];
    BLI_snprintf(time_label, sizeof(time_label), "Elapsed: %d:%02d", minutes, seconds);
    ui::uiDefBut(block,
             ui::ButtonType::Label,
             0,
             time_label,
             x,
             current_y,
             width,
             row_h,
             nullptr,
             0.0f,
             0.0f,
             "Time elapsed since job started");
  }

  /* Cancel button */
  current_y -= spacing;
  current_y -= row_h;
  total_height += spacing + row_h;

  ui::uiDefIconTextButO(block,
                    ui::ButtonType::But,
                    "MIXIE_OT_scene_recon_cancel",
                    blender::wm::OpCallContext::InvokeDefault,
                    ICON_CANCEL,
                    "Cancel",
                    x,
                    current_y,
                    width,
                    row_h,
                    "Cancel scene reconstruction");

  return total_height;
}

/* ============================================================================
 * COMPLETION SECTION DRAWING
 * ============================================================================ */

/**
 * Draw the completion section showing scene complete status.
 * Returns the total height used.
 */
static int draw_completion_section(ui::Block *block,
                                   PointerRNA *tab_ptr,
                                   int x,
                                   int y,
                                   int width)
{
  const int row_h = UI_UNIT_Y;

  /* Read phase and object count */
  char phase[64] = "";
  int total_objects = 0;

  PropertyRNA *phase_prop = RNA_struct_find_property(tab_ptr, "phase");
  if (phase_prop) {
    RNA_property_string_get(tab_ptr, phase_prop, phase);
  }

  PropertyRNA *total_obj_prop = RNA_struct_find_property(tab_ptr, "total_objects");
  if (total_obj_prop) {
    total_objects = RNA_property_int_get(tab_ptr, total_obj_prop);
  }

  /* Only show when phase is "completed" */
  if (!STREQ(phase, "completed")) {
    return 0;
  }

  int total_height = 0;
  int current_y = y;

  current_y -= row_h;
  total_height += row_h;

  ui::uiDefIconBut(block,
               ui::ButtonType::Label,
               0,
               ICON_CHECKMARK,
               x,
               current_y,
               dpi_scale(20),
               row_h,
               nullptr,
               0.0f,
               0.0f,
               std::nullopt);

  char complete_label[128];
  BLI_snprintf(complete_label, sizeof(complete_label), "  Scene Complete (%d objects)", total_objects);
  ui::uiDefBut(block,
           ui::ButtonType::Label,
           0,
           complete_label,
           x + dpi_scale(20),
           current_y,
           width - dpi_scale(20),
           row_h,
           nullptr,
           0.0f,
           0.0f,
           "Scene reconstruction completed successfully");

  return total_height;
}

/* ============================================================================
 * ERROR SECTION DRAWING
 * ============================================================================ */

/**
 * Draw the error section if an error occurred.
 * Returns the total height used.
 */
static int draw_error_section(ui::Block *block,
                              PointerRNA *tab_ptr,
                              int x,
                              int y,
                              int width)
{
  const int row_h = UI_UNIT_Y;

  char error_text[512] = "";
  PropertyRNA *error_prop = RNA_struct_find_property(tab_ptr, "error_text");
  if (error_prop) {
    RNA_property_string_get(tab_ptr, error_prop, error_text);
  }

  if (error_text[0] == '\0') {
    return 0;
  }

  int current_y = y - row_h;

  ui::uiDefIconBut(block,
               ui::ButtonType::Label,
               0,
               ICON_ERROR,
               x,
               current_y,
               dpi_scale(20),
               row_h,
               nullptr,
               0.0f,
               0.0f,
               std::nullopt);

  ui::uiDefBut(block,
           ui::ButtonType::Label,
           0,
           error_text,
           x + dpi_scale(20),
           current_y,
           width - dpi_scale(20),
           row_h,
           nullptr,
           0.0f,
           0.0f,
           "Error details");

  return row_h;
}

/* ============================================================================
 * TAB CONTENT DRAWING
 * ============================================================================ */

void draw_tab_scene_recon(const bContext *C, ui::Block *block, const TabContentLayout &layout)
{
  Scene *scene = CTX_data_scene(C);
  if (!scene) {
    return;
  }

  PointerRNA tab_ptr;
  if (!get_tab_properties(scene, tab_ptr)) {
    return;
  }

  const int row_h = UI_UNIT_Y;
  const int spacing = ui_element_spacing();
  const int sec_spacing = section_spacing();
  const int btn_h_lg = button_height_large();
  const int x = layout.content_x;
  const int w = layout.content_width;

  /* Get toggle state */
  PropertyRNA *use_selected_prop = RNA_struct_find_property(&tab_ptr, "use_selected_image");
  bool use_selected_image = use_selected_prop ?
                                RNA_property_boolean_get(&tab_ptr, use_selected_prop) :
                                false;

  /* Check if currently generating */
  bool is_generating = false;
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *gen_prop = RNA_struct_find_property(&scene_ptr, "mixie_scene_recon_is_generating");
  if (gen_prop) {
    is_generating = RNA_property_boolean_get(&scene_ptr, gen_prop);
  }

  /* Start from top of content area */
  int y = layout.tab_content_y + layout.tab_content_height;

  /* ---- About Section ---- */
  int about_height = draw_about_section(block,
                                        "Scene Reconstruction",
                                        "Reconstruct 3D scene from a single image",
                                        x,
                                        y,
                                        w);
  y -= about_height;
  y -= sec_spacing;

  /* ---- Use Moodboard Image Checkbox ---- */
  y -= row_h;
  draw_checkbox(block,
                &tab_ptr,
                "use_selected_image",
                "Use selected moodboard image",
                x,
                y,
                w,
                row_h);

  y -= sec_spacing;

  /* ---- Input Image Section ---- */
  y -= row_h;
  draw_section_label(block, "Input Image", x, y, w);

  y -= spacing;

  if (use_selected_image) {
    int selected_img_height = draw_selected_moodboard_image(block, scene, x, y, w);
    y -= selected_img_height;
  }
  else {
    int file_img_height = draw_file_picker_image_section(block, &tab_ptr, x, y, w);
    y -= file_img_height;
  }

  /* ---- Scene Description Prompt (when no moodboard and no file picked) ---- */
  if (!use_selected_image && !is_generating) {
    PropertyRNA *img_name_prop = RNA_struct_find_property(&tab_ptr, "image_name");
    char scene_img_name[256] = "";
    bool has_file_image = false;
    if (img_name_prop) {
      RNA_property_string_get(&tab_ptr, img_name_prop, scene_img_name);
      has_file_image = (scene_img_name[0] != '\0');
    }

    if (!has_file_image) {
      const int prompt_h = row_h * PROMPT_ROWS;

      y -= spacing;
      y -= row_h;
      draw_section_label(block, "Or describe a scene", x, y, w);

      y -= spacing;
      y -= prompt_h;
      draw_prompt_input(block, &tab_ptr, "prompt", x, y, w, prompt_h, nullptr);
    }
  }

  y -= sec_spacing;

  /* ---- Pipeline Settings Section ---- */
  if (!is_generating) {
    y -= row_h;
    draw_section_label(block, "Settings", x, y, w);

    y -= spacing;

    /* Generate Meshes checkbox */
    y -= row_h;
    draw_checkbox(block,
                  &tab_ptr,
                  "generate_mesh",
                  "Generate Meshes",
                  x,
                  y,
                  w,
                  row_h);

    y -= spacing;

    /* Min Object Size (pixels) */
    y -= row_h;
    PropertyRNA *min_mask_prop = RNA_struct_find_property(&tab_ptr, "min_mask_pixels");
    if (min_mask_prop) {
      ui::uiDefButR(block,
                ui::ButtonType::Num,
                0,
                "Min Object Size (px)",
                x,
                y,
                w,
                row_h,
                &tab_ptr,
                "min_mask_pixels",
                -1,
                100.0f,
                50000.0f,
                "Minimum segment size in pixels");
    }

    y -= spacing;

    /* Simplify Mesh checkbox */
    y -= row_h;
    draw_checkbox(block,
                  &tab_ptr,
                  "mesh_postprocess",
                  "Simplify Mesh",
                  x,
                  y,
                  w,
                  row_h);

    y -= spacing;

    /* Bake Textures checkbox */
    y -= row_h;
    draw_checkbox(block,
                  &tab_ptr,
                  "texture_baking",
                  "Bake Textures",
                  x,
                  y,
                  w,
                  row_h);

    y -= spacing;

    /* Vertex Colors checkbox */
    y -= row_h;
    draw_checkbox(block,
                  &tab_ptr,
                  "vertex_color",
                  "Vertex Colors",
                  x,
                  y,
                  w,
                  row_h);

    y -= spacing;

    /* Save to Asset Library checkbox */
    y -= row_h;
    draw_checkbox(block,
                  &tab_ptr,
                  "save_to_library",
                  "Save to Asset Library",
                  x,
                  y,
                  w,
                  row_h);

    /* Conditional: Asset Library Path (only when save_to_library is true) */
    PropertyRNA *save_lib_prop = RNA_struct_find_property(&tab_ptr, "save_to_library");
    bool save_to_library = save_lib_prop ? RNA_property_boolean_get(&tab_ptr, save_lib_prop) :
                                           false;
    if (save_to_library) {
      y -= spacing;
      y -= row_h;
      PropertyRNA *lib_path_prop = RNA_struct_find_property(&tab_ptr, "asset_library_path");
      if (lib_path_prop) {
        ui::uiDefButR(block,
                  ui::ButtonType::Text,
                  0,
                  "Library Path",
                  x,
                  y,
                  w,
                  row_h,
                  &tab_ptr,
                  "asset_library_path",
                  -1,
                  0.0f,
                  0.0f,
                  "Directory path for the asset library");
      }
    }

    y -= sec_spacing;
  }

  /* ---- Status Section (visible when generating) ---- */
  if (is_generating) {
    y -= row_h;
    draw_section_label(block, "Progress", x, y, w);

    y -= spacing;

    int status_height = draw_status_section(block, &tab_ptr, x, y, w);
    y -= status_height;

    y -= sec_spacing;
  }

  /* ---- Generate Button ---- */
  if (!is_generating) {
    y -= btn_h_lg;
    draw_generate_button_or_loader(block,
                                   scene,
                                   "MIXIE_OT_scene_recon_generate",
                                   "mixie_scene_recon_is_generating",
                                   x,
                                   y,
                                   w,
                                   btn_h_lg,
                                   "Reconstruct 3D scene from the input image");

    y -= sec_spacing;
  }

  /* ---- Error Section ---- */
  if (!is_generating) {
    int error_height = draw_error_section(block, &tab_ptr, x, y, w);
    y -= error_height;
    if (error_height > 0) {
      y -= sec_spacing;
    }
  }

  /* ---- Completion Section (Phase 2 complete) ---- */
  if (!is_generating) {
    int complete_height = draw_completion_section(block, &tab_ptr, x, y, w);
    y -= complete_height;
  }
}

}  // namespace blender::ed::mixie::moodboard::sidebar
