/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Common definitions and utilities for moodboard operators
 */

#pragma once

#include <algorithm>
#include <cmath>
#include <vector>
#include <string>
#include <sstream>

#include "MEM_guardedalloc.h"

#include "BLI_time.h"

#include "BLI_path_utils.hh"
#include "BLI_string.h"

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"

#include "BKE_context.hh"
#include "BKE_image.hh"
#include "BKE_lib_id.hh"
#include "BKE_main.hh"
#include "BKE_report.hh"

#include "IMB_imbuf.hh"
#include "IMB_imbuf_types.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "ED_screen.hh"
#include "ED_select_utils.hh"

#include "UI_view2d.hh"

#include "mixie_intern.hh"

namespace blender::ed::mixie {

/* -------------------------------------------------------------------- */
/** \name External Selection Functions
 * \{ */

/* External functions from mixie_select.cc */
extern int moodboard_find_image_under_mouse(PointerRNA *scene_ptr,
                                            float mouse_x,
                                            float mouse_y,
                                            float *r_pos_x,
                                            float *r_pos_y,
                                            float *r_scale,
                                            float *r_width,
                                            float *r_height);
extern int moodboard_find_textbox_under_mouse(PointerRNA *scene_ptr,
                                              float mouse_x,
                                              float mouse_y,
                                              float *r_pos_x,
                                              float *r_pos_y,
                                              float *r_width,
                                              float *r_height);
extern void moodboard_deselect_all(PointerRNA *scene_ptr);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Moodboard Data Structures
 * \{ */

/** Type of moodboard element */
enum MoodboardElementType { MOODBOARD_ELEMENT_IMAGE, MOODBOARD_ELEMENT_TEXTBOX, MOODBOARD_ELEMENT_GROUP };

/**
 * Find resize handle at mouse position for selected elements.
 * Returns handle index (0-7) or -1 if no handle found.
 * This checks handles of ALL selected images/textboxes, not just ones under the mouse.
 */
extern int moodboard_find_resize_handle_at_mouse(PointerRNA *scene_ptr,
                                                  float mouse_x,
                                                  float mouse_y,
                                                  float handle_tolerance,
                                                  int *r_element_index,
                                                  MoodboardElementType *r_element_type,
                                                  float *r_pos_x,
                                                  float *r_pos_y,
                                                  float *r_scale,
                                                  float *r_width,
                                                  float *r_height);

/** Context for moodboard selection operations */
struct MoodboardSelectionContext {
  PointerRNA *scene_ptr;
  PointerRNA item_ptr;
  PropertyRNA *sel_prop;
  int clicked_index;
  int group_index;
  bool is_image_selected;
  bool is_group_selected;
  bool is_double_click;
  bool extend_mode;
  MoodboardElementType element_type;
};

/** Move/resize interaction data */
struct MoodboardMoveData {
  MoodboardElementType element_type;
  int image_index;
  float initial_mouse_x;
  float initial_mouse_y;
  float initial_pos_x;
  float initial_pos_y;
  float initial_scale;
  float initial_width;
  float initial_height;
  float aspect_ratio;
  bool is_dragging;
  bool is_resizing;
  int resize_handle;
  bool is_empty_space_click;

  /* Multi-select support */
  bool has_stored_initial_positions;
  int selected_count;
  int selected_indices[MOODBOARD_MAX_SELECTED_IMAGES];
  float selected_initial_x[MOODBOARD_MAX_SELECTED_IMAGES];
  float selected_initial_y[MOODBOARD_MAX_SELECTED_IMAGES];
  float selected_initial_scale[MOODBOARD_MAX_SELECTED_IMAGES];
  float selected_initial_width[MOODBOARD_MAX_SELECTED_IMAGES];
  float selected_initial_height[MOODBOARD_MAX_SELECTED_IMAGES];
  float selected_aspect_ratio[MOODBOARD_MAX_SELECTED_IMAGES];

  /* Bounding box of all selected images for group scaling */
  float bbox_min_x;
  float bbox_min_y;
  float bbox_max_x;
  float bbox_max_y;
  float bbox_width;
  float bbox_height;

  /* Rotation of the clicked element (degrees) for correct resize anchoring */
  float initial_rotation;

  /* Text box resize support */
  int initial_font_size;

  /* Text box multi-select support */
  int selected_textbox_count;
  int selected_textbox_indices[MOODBOARD_MAX_SELECTED_IMAGES];
  float selected_textbox_initial_x[MOODBOARD_MAX_SELECTED_IMAGES];
  float selected_textbox_initial_y[MOODBOARD_MAX_SELECTED_IMAGES];

  /* Frame rate throttling for smoother interaction */
  double last_redraw_time;
  static constexpr double MIN_REDRAW_INTERVAL = 1.0 / 60.0; /* 60 FPS cap */
};

/** \} */

/* -------------------------------------------------------------------- */
/** \name Common Poll Function
 * \{ */

/**
 * Standard poll function for moodboard operators.
 * Returns true if we're in the Mixie space in moodboard mode.
 */
inline bool moodboard_poll(bContext *C)
{
  SpaceLink *sl = CTX_wm_space_data(C);
  if (sl && sl->spacetype == SPACE_MIXIE) {
    SpaceMixie *smixie = reinterpret_cast<SpaceMixie *>(sl);
    return smixie->mode == MIXIE_MODE_MOODBOARD;
  }
  return false;
}

/** \} */

}  // namespace blender::ed::mixie
