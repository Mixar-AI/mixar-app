/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 */

#pragma once

#include <string>

#include "BLI_map.hh"

/* rctf is stored by value in MoodboardGraphCache, so the full type is needed. */
#include "DNA_vec_types.h"

#include "RNA_types.hh"

/* internal exports only */

struct ARegion;
struct bContext;
struct Image;
struct ReportList;
struct Scene;
struct SpaceMixie;
struct View2D;
struct wmOperatorType;
struct wmRegionListenerParams;
struct wmWindowManager;

/* Mixie Mode Constants */
#define MIXIE_MODE_MOODBOARD 0

/* Moodboard Image Constants */
#define MOODBOARD_IMAGE_BASE_SIZE 700.0f
#define MOODBOARD_MEDIA_FRAME_PADDING 6.0f
#define MOODBOARD_MEDIA_FRAME_RADIUS 18.0f
#define MOODBOARD_IMAGE_MIN_SCALE 0.1f
#define MOODBOARD_IMAGE_MAX_SCALE 50.0f
#define MOODBOARD_IMAGE_SCALE_DELTA 0.1f
#define MOODBOARD_MAX_SELECTED_IMAGES 256
#define MOODBOARD_VIDEO_PLAY_RADIUS_PX 28.0f

/* Moodboard Interaction Constants */
#define MOODBOARD_HANDLE_TOLERANCE_PX 16.0f
#define MOODBOARD_DRAG_THRESHOLD_PX 5.0f

/* Moodboard Grid Constants */
#define MOODBOARD_GRID_SPACING 50.0f
#define MOODBOARD_GRID_DOT_RADIUS 2.5f
#define MOODBOARD_GRID_DOT_SEGMENTS 12
#define MOODBOARD_GRID_DOT_FADE_START_PX 1.5f
#define MOODBOARD_GRID_DOT_FADE_END_PX 3.0f

/* Moodboard Graph Constants */
/* Stack buffers for graph strings. Each MUST stay strictly larger than the
 * matching GRAPH_*_MAXLEN in `moodboard/constants.py`; reads go through
 * `mixie_rna_string_get_clamped` so an oversized legacy value truncates
 * instead of overflowing. */
#define MIXIE_GRAPH_ID_BUF 128     /* GRAPH_NODE_ID_MAXLEN / GRAPH_SOCKET_ID_MAXLEN */
#define MIXIE_GRAPH_LABEL_BUF 256  /* GRAPH_LABEL_MAXLEN */
#define MIXIE_GRAPH_WIDGET_BUF 64  /* GRAPH_WIDGET_MAXLEN */
#define MIXIE_GRAPH_NAMES_BUF 4096 /* GRAPH_OBJECT_NAMES_MAXLEN */
/** Inset of a node card's media preview from the card edge. */
#define MOODBOARD_GRAPH_PREVIEW_INSET 6.0f
#define MOODBOARD_GRAPH_SOCKET_RADIUS 10.0f
#define MOODBOARD_GRAPH_OUTPUT_RADIUS 13.0f
#define MOODBOARD_GRAPH_SOCKET_OFFSET 12.0f
#define MOODBOARD_GRAPH_LINK_RESOLUTION 24

/* Mixie3D Mode Constants */
#define SAM3D_PREVIEW_HEIGHT_RATIO 0.20f
#define SAM3D_PREVIEW_PADDING 15
#define SAM3D_PREVIEW_GAP 15
#define SAM3D_DELETE_BTN_SIZE 20
#define SAM3D_DELETE_BTN_MARGIN 5
#define SAM3D_SELECTION_BORDER 3
#define SAM3D_DELETE_X_MARGIN 4

namespace blender::ed::mixie {

/* -------------------------------------------------------------------- */
/** \name Mode Drawing Functions
 * \{ */

/** Draw sam3d segmentation mode */
void mixie_draw_sam3d_mode(const bContext *C, ARegion *region);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Moodboard Drawing (mixie_draw_moodboard.cc)
 * \{ */

/** Draw moodboard mode (grid, images, textboxes, selection overlay) */
void mixie_draw_moodboard_mode(const bContext *C, ARegion *region);

/** Free the sRGB texture cache used by moodboard image drawing. */
void mixie_moodboard_free_texture_cache();

/** \} */

/* -------------------------------------------------------------------- */
/** \name Mixie3D Drawing (mixie_draw_sam3d.cc)
 * \{ */

/** Draw a Mixie3D preview thumbnail */
void mixie_draw_sam3d_preview_thumbnail(Image *image,
                                        int x,
                                        int y,
                                        int width,
                                        int height,
                                        bool is_selected,
                                        bool show_delete);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Selection Utilities (mixie_select.cc)
 * \{ */

/**
 * Find moodboard image under mouse position.
 * Returns image index or -1 if not found.
 * Optionally returns image position, scale, width and height.
 */
int moodboard_find_image_under_mouse(PointerRNA *scene_ptr,
                                     float mouse_x,
                                     float mouse_y,
                                     float *r_pos_x,
                                     float *r_pos_y,
                                     float *r_scale,
                                     float *r_width,
                                     float *r_height);

/**
 * Find moodboard textbox under mouse position.
 * Returns textbox index or -1 if not found.
 */
int moodboard_find_textbox_under_mouse(PointerRNA *scene_ptr,
                                       float mouse_x,
                                       float mouse_y,
                                       float *r_pos_x,
                                       float *r_pos_y,
                                       float *r_width,
                                       float *r_height);

int moodboard_find_action_node_under_mouse(PointerRNA *scene_ptr,
                                           float mouse_x,
                                           float mouse_y,
                                           rctf *r_rect);
/** Media-preview rect of a node card. Shared by draw, toolbar and hit-test. */
void moodboard_graph_node_preview_bounds(const rctf &node_rect, rctf *r_bounds);
/** Index into `mixie_moodboard_images` of the media a node owns, or -1. */
int moodboard_find_embedded_media_index(PointerRNA *scene_ptr, const char *node_id);
/**
 * Index into `mixie_moodboard_images` of the movie rendered inside the action
 * node under the cursor, or -1. Deliberately the media index, not the node
 * index: playback state and the hover monitor are both keyed on it.
 */
int moodboard_find_node_preview_video_under_mouse(PointerRNA *scene_ptr,
                                                  float mouse_x,
                                                  float mouse_y,
                                                  rctf *r_node_rect);
int moodboard_find_asset_node_under_mouse(PointerRNA *scene_ptr,
                                          float mouse_x,
                                          float mouse_y,
                                          rctf *r_rect);
int moodboard_find_link_under_mouse(PointerRNA *scene_ptr,
                                    View2D *v2d,
                                    int mouse_region_x,
                                    int mouse_region_y,
                                    float max_distance_px);

/**
 * Copy an RNA string into a fixed buffer, truncating instead of overflowing.
 *
 * ``RNA_string_get`` is strcpy-shaped: it writes the property's whole value
 * with no regard for the destination size. Every graph string property now
 * declares a ``maxlen`` smaller than its buffer (see the GRAPH_*_MAXLEN block
 * in ``moodboard/constants.py``), but ``maxlen`` is only enforced on
 * assignment — a .blend written before those limits existed can still carry a
 * longer value, and that value reaches this code during draw. Reads therefore
 * clamp as well. No allocation on the common path.
 */
void mixie_rna_string_get_clamped(PointerRNA *ptr,
                                  const char *name,
                                  char *dst,
                                  int dst_maxncpy);
void mixie_rna_property_string_get_clamped(PointerRNA *ptr,
                                           PropertyRNA *prop,
                                           char *dst,
                                           int dst_maxncpy);

struct MoodboardGraphSocketHit {
  char node_id[MIXIE_GRAPH_ID_BUF];
  char socket_id[MIXIE_GRAPH_ID_BUF];
  float x;
  float y;
};

/**
 * One pass over the canvas collections, reused by every link in a draw or
 * hit-test sweep. Built by #moodboard_graph_cache_build and passed to
 * #moodboard_graph_link_endpoints; without it each link re-scans the whole
 * image collection and re-acquires that image's ImBuf just to read its aspect.
 */
struct MoodboardGraphCache {
  /** node_id -> canvas rect, for media, action and asset nodes alike. */
  blender::Map<std::string, rctf> outputs;
  /** node_id -> action node, the only nodes that own input sockets. */
  blender::Map<std::string, PointerRNA> action_nodes;
};

void moodboard_graph_cache_build(PointerRNA *scene_ptr, MoodboardGraphCache *cache);

void moodboard_graph_link_curve_coords(
    float x1,
    float y1,
    float x2,
    float y2,
    float r_coords[MOODBOARD_GRAPH_LINK_RESOLUTION + 1][2]);
bool moodboard_graph_link_endpoints(PointerRNA *scene_ptr,
                                    PointerRNA *link,
                                    float *r_x1,
                                    float *r_y1,
                                    float *r_x2,
                                    float *r_y2,
                                    const MoodboardGraphCache *cache = nullptr);
bool moodboard_graph_action_socket_position(
    PointerRNA *node, int socket_index, float *r_x, float *r_y);
bool moodboard_find_output_socket_under_mouse(PointerRNA *scene_ptr,
                                               View2D *v2d,
                                               int mouse_region_x,
                                               int mouse_region_y,
                                               MoodboardGraphSocketHit *r_hit);
bool moodboard_find_input_socket_under_mouse(PointerRNA *scene_ptr,
                                              View2D *v2d,
                                              int mouse_region_x,
                                              int mouse_region_y,
                                              MoodboardGraphSocketHit *r_hit);
/** Conservative canvas-space bounds of the link curve, for view culling. */
void moodboard_graph_link_bounds(float x1, float y1, float x2, float y2, rctf *r_bounds);
void moodboard_graph_link_drag_begin(Scene *scene, float x, float y);
void moodboard_graph_link_drag_update(Scene *scene, float x, float y);
void moodboard_graph_link_drag_end(Scene *scene);
/** Drop any in-flight link-drag preview regardless of which scene owns it. */
void moodboard_graph_link_drag_reset();
bool moodboard_graph_link_drag_preview(
    Scene *scene, float *r_x1, float *r_y1, float *r_x2, float *r_y2);

/** Whether the moodboard item at \a index references a movie datablock. */
bool moodboard_item_is_video(PointerRNA *scene_ptr, int index);

/** Toggle runtime-only playback of a movie directly on its moodboard block. */
bool moodboard_toggle_video_playback(bContext *C,
                                     PointerRNA *scene_ptr,
                                     int index,
                                     ReportList *reports);

/** Current inline playback frame and state for a movie image. */
int moodboard_video_playback_frame(Image *image, bool *r_is_playing);

/** Stop inline movie playback and its redraw timer. */
void mixie_moodboard_video_playback_shutdown(wmWindowManager *wm);

/** Deselect all moodboard content, graph nodes, and links. */
void moodboard_deselect_all(PointerRNA *scene_ptr);

/** Get sam3d preview index at position */
int mixie_get_sam3d_preview_at_position(const bContext *C,
                                        const ARegion *region,
                                        int mouse_x,
                                        int mouse_y);

/** Get sam3d preview delete button at position, returns index or -1 */
int mixie_get_sam3d_preview_delete_at_position(const bContext *C,
                                               ARegion *region,
                                               int mouse_x,
                                               int mouse_y);

/** \} */

}  // namespace blender::ed::mixie

/* -------------------------------------------------------------------- */
/** \name Operator Registration (C linkage)
 * \{ */

/* mixie_header.cc */
void mixie_header_region_init(wmWindowManager *wm, ARegion *region);
void mixie_header_region_draw(const bContext *C, ARegion *region);

/* mixie_dragdrop.cc */
void mixie_dropboxes();

/* mixie_ops.cc - General operators */
void MIXIE_OT_sam3d_preview_select(wmOperatorType *ot);
void MIXIE_OT_sam3d_preview_delete(wmOperatorType *ot);

/* mixie_moodboard_ops.cc - Moodboard operators */
void MIXIE_OT_moodboard_drop_image(wmOperatorType *ot);
void MIXIE_OT_moodboard_select_image(wmOperatorType *ot);
void MIXIE_OT_moodboard_graph_select(wmOperatorType *ot);
void MIXIE_OT_moodboard_context_menu(wmOperatorType *ot);
void MIXIE_OT_moodboard_video_hover(wmOperatorType *ot);
void MIXIE_OT_moodboard_zoom(wmOperatorType *ot);
void MIXIE_OT_moodboard_ensure_visible(wmOperatorType *ot);
void MIXIE_OT_moodboard_box_select(wmOperatorType *ot);
void MIXIE_OT_moodboard_generate_box_mask(wmOperatorType *ot);
void MIXIE_OT_moodboard_generate_lasso_mask(wmOperatorType *ot);
void MIXIE_OT_moodboard_crop_image(wmOperatorType *ot);

/** \} */
