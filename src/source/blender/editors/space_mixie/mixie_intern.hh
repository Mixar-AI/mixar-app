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
#include "BLI_set.hh"

/* rctf is stored by value in MoodboardGraphCache, so the full type is needed. */
#include "DNA_vec_types.h"

#include "RNA_types.hh"

/* Resize handles and canvas frames: the canvas geometry shared by draw,
 * hit-test and drag. Split out for the 500-line rule; included here so
 * every translation unit that includes this header still sees them. */
#include "mixie_moodboard_hit_geometry.hh"

/* internal exports only */

namespace blender {
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
}  // namespace blender
using ARegion = blender::ARegion;
using bContext = blender::bContext;
using Image = blender::Image;
using ReportList = blender::ReportList;
using Scene = blender::Scene;
using SpaceMixie = blender::SpaceMixie;
using View2D = blender::View2D;
using wmOperatorType = blender::wmOperatorType;
using wmRegionListenerParams = blender::wmRegionListenerParams;
using wmWindowManager = blender::wmWindowManager;

/* Mixie Mode Constants */
#define MIXIE_MODE_MOODBOARD 0

/* Moodboard Image Constants */
#define MOODBOARD_IMAGE_BASE_SIZE 700.0f
#define MOODBOARD_MEDIA_FRAME_PADDING 6.0f
/* Square media stays uncropped: inner radius zero means outer radius = inset. */
#define MOODBOARD_MEDIA_FRAME_RADIUS MOODBOARD_MEDIA_FRAME_PADDING
#define MOODBOARD_IMAGE_MIN_SCALE 0.1f
#define MOODBOARD_IMAGE_MAX_SCALE 50.0f
#define MOODBOARD_IMAGE_SCALE_DELTA 0.1f
#define MOODBOARD_MAX_SELECTED_IMAGES 256
#define MOODBOARD_VIDEO_PLAY_RADIUS_PX 28.0f
/* The play affordance is a fixed SCREEN size -- but only until it starts to
 * crowd the frame behind it. Past this fraction of the tile's shorter side it
 * shrinks WITH the tile, so zooming out can never leave a play button wider
 * than the video it sits on. */
#define MOODBOARD_VIDEO_PLAY_MAX_FRACTION 0.22f

/* Moodboard Interaction Constants */
#define MOODBOARD_HANDLE_TOLERANCE_PX 16.0f
#define MOODBOARD_DRAG_THRESHOLD_PX 5.0f
/* A resize handle is a fixed SCREEN size converted through the view scale: it
 * is an affordance, not part of the picture, so it stays equally aimable at
 * every zoom. */
#define MOODBOARD_RESIZE_HANDLE_PX 12.0f
/* Slide amount at which the Zen VIEW_3D drawer hosts a live Mixie canvas.
 * The draw pass shifts `v2d.cur` then restores it, so hit-test matches paint
 * only once the offset is essentially gone. Keep in lockstep with
 * `VIEW3D_MOODBOARD_DRAWER_CANVAS_MIN_AMOUNT`. */
#define MIXIE_MOODBOARD_DRAWER_ACTIVE_AMOUNT 0.98f

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
#define MIXIE_GRAPH_ERROR_BUF 768  /* GRAPH_ERROR_MAXLEN */
#define MIXIE_GRAPH_DESCRIPTION_BUF 768 /* GRAPH_DESCRIPTION_MAXLEN */
#define MIXIE_GRAPH_PROGRESS_BUF 128 /* GRAPH_PROGRESS_MAXLEN */
#define MIXIE_GRAPH_NOTICE_BUF 256 /* GRAPH_NOTICE_MAXLEN */
/* Canvas grid EVERYTHING snaps to while Ctrl is held during a move -- nodes,
 * images, videos and text boxes alike, or snapping one kind against another
 * would be impossible. Canvas units, so the grid belongs to the board rather
 * than to the current zoom: two items snapped at different zoom levels still
 * line up. Duplicated as `GRAPH_SNAP_GRID` in moodboard/constants.py for the
 * Python grab modal; the two MUST agree and a test pins that. */
#define MOODBOARD_SNAP_GRID 40.0f
/* The row floating just ABOVE a node card: its name on the left, and on the
 * right either its live state (while generating) or the Edit/Export icons
 * (once finished) -- never both, because a node is one or the other. Nothing
 * sits on the card itself, so the result is never covered.
 *
 * Both metrics are multiplied by UI_SCALE_FAC at the point of use: the row has
 * to fit TEXT, which does not scale with the card. The two are shared by the
 * painter and the button layout so they cannot drift onto different lines. */
#define MOODBOARD_NODE_HEADER_LIFT 12.0f
#define MOODBOARD_NODE_HEADER_ROW_H 30.0f
/* Floor on the in-place rename field above a reference tile (canvas units,
 * x UI_SCALE_FAC): the field spans the tile's width, but a tile shrunk below
 * this still needs room to read and type a name. */
#define MOODBOARD_MEDIA_RENAME_MIN_W 180.0f
/* Display-only echo of a draft node's prompt inside its tile. Deliberately far
 * below the prompt's 4096 maxlen: the clamped read truncates, which is exactly
 * what a one-line preview wants. Not part of the maxlen<buffer pairings. */
#define MIXIE_GRAPH_PROMPT_PREVIEW_BUF 192
/* Minimum on-screen node size before the floating prompt/toolbar controls
 * draw. Shared with the draft-hint text so exactly one of the two shows. */
#define MOODBOARD_GRAPH_CONTROLS_MIN_PX_X 360
#define MOODBOARD_GRAPH_CONTROLS_MIN_PX_Y 220
/** Inset of a node card's media preview from the card edge. */
#define MOODBOARD_GRAPH_PREVIEW_INSET 6.0f
/* Width bounds for a resized action card, inside the `width` RNA property's
 * own min/max (140..1400). The card is resized by the SHARED corner handles
 * (see the Resize Handles block below), keeping the aspect it had at drag
 * start -- the card tracks its result image, see
 * node_schema.refresh_node_height. */
#define MOODBOARD_ACTION_NODE_MIN_W 360.0f
#define MOODBOARD_ACTION_NODE_MAX_W 1200.0f
/* Socket centers/offset remain in canvas units. Draw and hit radii are bounded
 * in UI pixels through the shared helpers, including the QA target provider. */
#define MOODBOARD_GRAPH_SOCKET_RADIUS 12.0f
#define MOODBOARD_GRAPH_OUTPUT_RADIUS 15.0f
#define MOODBOARD_GRAPH_SOCKET_OFFSET 14.0f
#define MOODBOARD_GRAPH_LINK_RESOLUTION 24

/* Canvas frames (grouping). A frame is a first-class canvas object with its
 * own rect, so every metric below describes THE FRAME rather than being
 * derived from whatever happens to be inside it.
 *
 * `name` is the only string the canvas reads off a frame, and it follows the
 * GRAPH_*_MAXLEN <-> MIXIE_*_BUF rule: FRAME_NAME_MAXLEN (96, moodboard's
 * constants.py) stays strictly below this buffer, and the read still clamps. */
#define MIXIE_FRAME_NAME_BUF 128
/* Floors, mirrored as FRAME_MIN_WIDTH / FRAME_MIN_HEIGHT in constants.py --
 * the C++ resize drag and the Python geometry must not disagree about how
 * small a frame may get. */
#define MOODBOARD_FRAME_MIN_W 220.0f
#define MOODBOARD_FRAME_MIN_H 160.0f
#define MOODBOARD_FRAME_RADIUS 20.0f
/* Border thickness in CANVAS units, so it zooms with the frame like the socket
 * radii do. The TOP edge is deliberately thicker: it is the frame's drag
 * handle and its primary click target, the same job the header strip does on a
 * node card, and it has to be aimable. */
#define MOODBOARD_FRAME_BORDER 7.0f
#define MOODBOARD_FRAME_TOP_BORDER 26.0f
/* The washed fill. On the board's pure-black canvas a pastel at low alpha
 * reads as a faint coloured haze, which is the intent; DESATURATING toward
 * white (the instinct from a white canvas) would instead turn it grey and cost
 * the frame its identity. So the two states differ in alpha only, never in
 * saturation. */
#define MOODBOARD_FRAME_FILL_ALPHA 0.07f
#define MOODBOARD_FRAME_FILL_ALPHA_SELECTED 0.12f
#define MOODBOARD_FRAME_BORDER_ALPHA 0.55f
#define MOODBOARD_FRAME_BORDER_ALPHA_SELECTED 1.0f
/* The click zone is wider than the paint: even a 7-canvas-unit line falls under
 * a couple of pixels when zoomed out, and an edge the user can see but cannot
 * grab is worse than no edge. Converted through the view scale with a pixel
 * floor. */
#define MOODBOARD_FRAME_HIT_SLOP 1.8f
#define MOODBOARD_FRAME_HIT_MIN_PX 6.0f
/* Floor for the in-place rename field above a frame, in UI pixels: a narrow
 * frame still gets a field wide enough to read the name being typed. */
#define MOODBOARD_FRAME_RENAME_MIN_W 180.0f
/* Frame name: sized WITH the canvas exactly like a selected media's name, so a
 * frame drawn half as wide carries a name half as tall. Base point size at
 * zoom 1 before the DPI factor, then clamped, then fitted to the frame's own
 * width (see mixie_draw_moodboard_frame_labels). A frame name is ALWAYS drawn,
 * selected or not -- it is the one thing the rect itself cannot say, and it is
 * how frames are told apart at a glance. */
#define MOODBOARD_FRAME_LABEL_SIZE_PX 13.0f
#define MOODBOARD_FRAME_LABEL_MIN_PX 8.0f
#define MOODBOARD_FRAME_LABEL_MAX_PX 30.0f
#define MOODBOARD_FRAME_LABEL_MAX_CHARS 28
#define MOODBOARD_FRAME_LABEL_HEAD_CHARS 14
#define MOODBOARD_FRAME_LABEL_TAIL_CHARS 13

/* Mixie3D Mode Constants */
#define SAM3D_PREVIEW_HEIGHT_RATIO 0.20f
#define SAM3D_PREVIEW_PADDING 15
#define SAM3D_PREVIEW_GAP 15
#define SAM3D_DELETE_BTN_SIZE 20
#define SAM3D_DELETE_BTN_MARGIN 5
#define SAM3D_SELECTION_BORDER 3
#define SAM3D_DELETE_X_MARGIN 4

namespace blender::ed::mixie {

float moodboard_socket_radius_px(const View2D *v2d, bool output = false);
float moodboard_socket_hit_radius_px(const View2D *v2d, bool output = false);
float moodboard_graph_input_radius_px(PointerRNA *node, int socket_index, const View2D *v2d);

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

/* sRGB texture cache (mixie_draw_moodboard_texture_cache.cc). Bracket one draw
 * pass with begin/end: end evicts whatever that pass did not touch. */
void mixie_moodboard_texture_cache_frame_begin();
void mixie_moodboard_texture_cache_frame_end();
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
/** True when the action node is a MASK_DETAIL node: it has a fixed square card
 * (controls over an in-card mask thumbnail), so it is not resizable. */
/** Is the item owning this graph node id selected? The graph cache is keyed by
 * id and carries only rects, so framing has to resolve selection separately. */
bool moodboard_graph_node_id_selected(PointerRNA *scene_ptr, const char *node_id);
bool moodboard_node_is_mask_detail(PointerRNA *node);
/** Index into `mixie_moodboard_images` of the media a node owns, or -1. */
int moodboard_find_embedded_media_index(PointerRNA *scene_ptr, const char *node_id);
/**
 * In-place rename of a reference (mixie_moodboard_ops_rename_media.cc).
 * Runtime-only, keyed on the scene's session uid; the draw pass asks whether a
 * tile is being renamed and reports the end of the edit back.
 */
bool moodboard_media_rename_is_active(const Scene *scene, const char *media_id);
void moodboard_media_rename_end();
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
  /** "to_node_id|to_socket" of every link, so sockets can draw occupancy. */
  blender::Set<std::string> occupied_inputs;
};

void moodboard_graph_cache_build(PointerRNA *scene_ptr, MoodboardGraphCache *cache);

/** Key of one input socket in #MoodboardGraphCache::occupied_inputs. */
std::string moodboard_graph_socket_key(const char *node_id, const char *socket_id);

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
/** Is a noodle currently being dragged in this scene? Sockets name themselves
 * while one is, which is exactly when the user needs to read them. */
bool moodboard_graph_link_drag_active(Scene *scene);
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

/**
 * Canvas-unit radius of a movie tile's centred play/pause affordance.
 *
 * The button is a fixed pixel size, so it converts through the view scale, and
 * is then capped at #MOODBOARD_VIDEO_PLAY_MAX_FRACTION of the tile's shorter
 * side. Draw and BOTH hit-tests (standalone tile, node preview) share this one
 * definition -- otherwise the pixels the user aims at and the region that
 * responds drift apart at some zoom.
 */
float moodboard_video_play_radius(View2D *v2d, const rctf &media_rect);

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
/** \name Operator Registration
 * \{ */

namespace blender {

/* mixie_header.cc */
void mixie_header_region_init(wmWindowManager *wm, ARegion *region);
void mixie_header_region_draw(const bContext *C, ARegion *region);

/* mixie_dragdrop.cc */
void mixie_dropboxes();

/* mixie_moodboard_qa_targets.cc */
void mixie_moodboard_qa_targets_register();

/* mixie_ops.cc - General operators */
void MIXIE_OT_sam3d_preview_select(wmOperatorType *ot);
void MIXIE_OT_sam3d_preview_delete(wmOperatorType *ot);

/* mixie_moodboard_ops.cc - Moodboard operators */
void MIXIE_OT_moodboard_drop_image(wmOperatorType *ot);
void MIXIE_OT_moodboard_select_image(wmOperatorType *ot);
void MIXIE_OT_moodboard_graph_select(wmOperatorType *ot);
void MIXIE_OT_moodboard_frame_select(wmOperatorType *ot);
void MIXIE_OT_moodboard_rename_frame(wmOperatorType *ot);
void MIXIE_OT_moodboard_context_menu(wmOperatorType *ot);
void MIXIE_OT_moodboard_video_hover(wmOperatorType *ot);
void MIXIE_OT_moodboard_zoom(wmOperatorType *ot);
void MIXIE_OT_moodboard_ensure_visible(wmOperatorType *ot);
void MIXIE_OT_moodboard_frame(wmOperatorType *ot);
void MIXIE_OT_moodboard_preview_media(wmOperatorType *ot);
void MIXIE_OT_moodboard_rename_media(wmOperatorType *ot);
void MIXIE_OT_moodboard_box_select(wmOperatorType *ot);
void MIXIE_OT_moodboard_generate_box_mask(wmOperatorType *ot);
void MIXIE_OT_moodboard_generate_lasso_mask(wmOperatorType *ot);
void MIXIE_OT_moodboard_crop_image(wmOperatorType *ot);

}  // namespace blender

/** \} */
