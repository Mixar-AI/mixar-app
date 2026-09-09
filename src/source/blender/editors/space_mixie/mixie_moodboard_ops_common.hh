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
#include "BLI_vector.hh"
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

/* Which graph collection a node index refers to. Shared because the selection
 * primitives below are, and both units index the same two collections. */
enum GraphNodeKind { GRAPH_ACTION = 0, GRAPH_ASSET = 1 };

/* mixie_moodboard_ops_graph.cc -- graph selection primitives, shared with the
 * context-menu unit so "what is selected" has exactly one implementation. */
/** Clear the selection on every graph node and the active-node id with it. */
void moodboard_graph_deselect_nodes(PointerRNA *scene_ptr);
/** Make one node the whole selection; `r_node` receives it when non-null. */
void moodboard_graph_select_node(PointerRNA *scene_ptr,
                                 GraphNodeKind kind,
                                 int index,
                                 PointerRNA *r_node);
/** Select one link by index, clearing any other. False when it does not exist. */
bool moodboard_graph_select_link(PointerRNA *scene_ptr, int index);

/* mixie_moodboard_ops_preview.cc */
/** The Image datablock a moodboard item references, or null. Shared so the
 * preview window resolves media exactly the way playback does. */
Image *moodboard_item_image(PointerRNA *scene_ptr, int index);

/* mixie_moodboard_ops_graph_video.cc */
/**
 * Handle a press on a node-owned movie's play affordance (or a double-click on
 * its tile). Returns true when the gesture was the node's to take, with the
 * operator status to return in `r_status`.
 */
bool moodboard_graph_node_video_click(bContext *C,
                                      PointerRNA *scene_ptr,
                                      View2D *v2d,
                                      const rctf &node_rect,
                                      const char *node_id,
                                      float mouse_x,
                                      float mouse_y,
                                      bool double_click,
                                      ReportList *reports,
                                      wmOperatorStatus *r_status);

/* mixie_moodboard_ops_graph_resize.cc */
/** Everything a card-resize drag needs to remember from the moment it began.
 * Owned by the graph select/move operator's customdata; the resize unit is
 * stateless and works entirely off this. */
struct MoodboardGraphResizeState {
  float initial_mouse_x;
  float initial_mouse_y;
  float initial_y;
  float initial_width;
  float initial_height;
};
/** True when the press landed on a node's bottom-right resize grip; fills
 * `r_state` with the drag origin when it did. */
bool moodboard_graph_resize_grip_hit(PointerRNA *node,
                                     const rctf &node_rect,
                                     float mouse_x,
                                     float mouse_y,
                                     MoodboardGraphResizeState *r_state);
/** Drive one event of an in-progress card resize. Sets `r_done` when the
 * gesture ended (release, or Esc/right-click, which restores the card), which
 * is the caller's cue to free its customdata. */
wmOperatorStatus moodboard_graph_resize_modal(bContext *C,
                                              ARegion *region,
                                              PointerRNA *node,
                                              const MoodboardGraphResizeState &state,
                                              const wmEvent *event,
                                              bool *r_done);

/* mixie_moodboard_ops_graph_link.cc */
/**
 * Decide what a released noodle meant: connect to the input socket under the
 * cursor, connect to the inference card it landed on, or — on free canvas after
 * an actual drag — open the continuation menu anchored at the drop point.
 * \a moved distinguishes a drag from a plain click on the output handle.
 */
wmOperatorStatus moodboard_graph_link_release(bContext *C,
                                              PointerRNA *scene_ptr,
                                              View2D *v2d,
                                              const wmEvent *event,
                                              const char *from_node_id,
                                              bool moved,
                                              bool detached);
/**
 * Press on a CONNECTED input socket: remove its link and report the source it
 * came from, so the caller carries on as an ordinary link drag from that
 * source. Returns false when the press was not on an occupied input, in which
 * case nothing was changed.
 */
bool moodboard_graph_detach_input(bContext *C,
                                  PointerRNA *scene_ptr,
                                  View2D *v2d,
                                  const wmEvent *event,
                                  char *r_from_node_id,
                                  int from_node_id_maxncpy);
/** Forget any recorded drop point, so a later menu places beside its source. */
void moodboard_graph_clear_link_drop_anchor(PointerRNA *scene_ptr);

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

/* -------------------------------------------------------------------- */
/** \name Drag Set
 *
 * What a drag carries. See mixie_moodboard_move_selection.cc -- a board has
 * two drag operators (media and graph cards) and one selection, so both build
 * the moved set through the same capture.
 * \{ */

enum MoodboardDragKinds {
  MOODBOARD_DRAG_IMAGES = (1 << 0),
  MOODBOARD_DRAG_TEXTBOXES = (1 << 1),
  MOODBOARD_DRAG_NODES = (1 << 2), /* Action + asset cards. */
  MOODBOARD_DRAG_ALL = MOODBOARD_DRAG_IMAGES | MOODBOARD_DRAG_TEXTBOXES |
                       MOODBOARD_DRAG_NODES,
};

struct MoodboardDragItem {
  /* Static string from the table in mixie_moodboard_move_selection.cc, so the
   * entry owns no memory and the set stays trivially copyable. */
  const char *collection;
  int index;
  float initial_x;
  float initial_y;
};

struct MoodboardDragSet {
  blender::Vector<MoodboardDragItem> items;
};

/** Record every selected item of `kinds` and the position it starts at. */
void moodboard_drag_set_capture(PointerRNA *scene_ptr,
                                MoodboardDragKinds kinds,
                                MoodboardDragSet *drag);

/** Place the whole set at its captured start offset by (delta_x, delta_y). */
void moodboard_drag_set_apply(PointerRNA *scene_ptr,
                              const MoodboardDragSet &drag,
                              float delta_x,
                              float delta_y);

/** Put the set back where the drag found it (Esc / right-click). */
void moodboard_drag_set_restore(PointerRNA *scene_ptr, const MoodboardDragSet &drag);

/** \} */

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

  /* Cards travelling with this media drag -- inference and 3D asset nodes.
   * They live in a MoodboardDragSet rather than in arrays beside the image and
   * text-box ones above, because the graph drag has to carry the same set the
   * other way round and there must be one capture, not two. The media arrays
   * stay as they are: they also feed resizing, which cards do not share. */
  MoodboardDragSet node_drag;

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
