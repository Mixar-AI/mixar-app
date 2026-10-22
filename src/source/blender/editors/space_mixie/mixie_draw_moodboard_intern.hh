/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Internal declarations for moodboard drawing functions
 */

#pragma once

#include <algorithm>
#include <cmath>
#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_listbase.h"
#include "BLI_math_vector.h"
#include "BLI_rect.h"

#include "BLF_api.hh"

#include "BKE_context.hh"
#include "BKE_image.hh"

#include "DNA_image_types.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"

#include "GPU_immediate.hh"
#include "GPU_matrix.hh"
#include "GPU_state.hh"
#include "GPU_texture.hh"

#include "BIF_glutil.hh"

#include "IMB_colormanagement.hh"
#include "IMB_imbuf.hh"
#include "IMB_imbuf_types.hh"

#include "RNA_access.hh"

#include "UI_view2d.hh"

#include "mixie_intern.hh"

namespace blender::ui {
struct Block;
/* The tooltip helpers below take a button; the UI headers that define it are
 * not pulled in here, and only the pointer type is needed. */
struct Button;
}  // namespace blender::ui

namespace blender::ed::mixie {

/**
 * The cached sRGB GPU texture for \a image (mixie_draw_moodboard_texture_cache.cc).
 * Raw sRGB bytes, so the board's colours survive; null when it cannot be built.
 */
gpu::Texture *mixie_moodboard_srgb_texture(Image *image, ImageUser *image_user);

/**
 * Pixel size of \a image for layout.
 *
 * A matching draw stamp (session uid, depsgraph update count, last frame and
 * the requested frame) returns the cached size without taking the image lock.
 * Session uid 0 or a missing runtime never hits that cache. False leaves
 * \a r_width and \a r_height unchanged.
 */
bool mixie_moodboard_image_size(Image *image, ImageUser *image_user, int *r_width, int *r_height);
/** Height / width for canvas tiles. 1 when the buffer cannot be read. */
float mixie_moodboard_image_aspect(Image *image);

/* -------------------------------------------------------------------- */
/** \name RNA Property Caching
 *
 * Cache PropertyRNA pointers to avoid repeated string-based lookups every frame.
 * \{ */

/** Cached RNA property pointers for moodboard image items. */
struct MoodboardImageProps {
  PropertyRNA *image;
  PropertyRNA *display_image;  /* Segment overlay display image (if set, draw this instead) */
  PropertyRNA *embedded_node_id;
  PropertyRNA *position_x;
  PropertyRNA *position_y;
  PropertyRNA *scale;
  PropertyRNA *rotation;
  PropertyRNA *flip_horizontal;
  PropertyRNA *flip_vertical;
  PropertyRNA *selected;
  PropertyRNA *annotations;
  PropertyRNA *show_annotations;
  bool initialized;
};

/** Cached RNA property pointers for moodboard textbox items. */
struct MoodboardTextboxProps {
  PropertyRNA *text;
  PropertyRNA *position_x;
  PropertyRNA *position_y;
  PropertyRNA *width;
  PropertyRNA *height;
  PropertyRNA *font_size;
  PropertyRNA *rotation;
  PropertyRNA *text_color;
  PropertyRNA *background_color;
  PropertyRNA *align;
  PropertyRNA *bold;
  PropertyRNA *italic;
  PropertyRNA *selected;
  bool initialized;
};

/* Global property caches - defined in mixie_draw_moodboard.cc */
extern MoodboardImageProps g_img_props;
extern MoodboardTextboxProps g_tb_props;

void init_image_property_cache(PointerRNA *itemptr);
void init_textbox_property_cache(PointerRNA *itemptr);

/** \} */

/* -------------------------------------------------------------------- */
/** \name View Frustum Culling
 * \{ */

/**
 * Check if a rectangle is within the visible view area.
 * Used for early exit to avoid processing images/textboxes outside the viewport.
 */
bool is_rect_in_view(View2D *v2d, float x, float y, float w, float h);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Drawing Functions (Internal)
 * \{ */

/** Draw selection overlay with resize handles for a selected element */
void mixie_draw_moodboard_selection_overlay(View2D *v2d, float x, float y, float w, float h);

/**
 * Paint the four corner resize squares of \a rect.
 *
 * Positions come from `moodboard_resize_handle_positions`, the ONE definition
 * the hit-test reads, so the squares and the region that responds cannot part
 * company. Expects an already-bound `GPU_SHADER_3D_UNIFORM_COLOR` and the
 * caller's `pos` attribute -- both callers (the media/text selection overlay
 * and the node card pass) are already inside one.
 */
void mixie_draw_moodboard_resize_handles(
    View2D *v2d, uint pos, float x, float y, float w, float h);

/** Draw the shared neutral node frame behind imported image/movie content. */
void mixie_draw_moodboard_media_frame(float x, float y, float w, float h, bool selected);

/** Paint `rect` as a liquid-glass moodboard pane (MIXAR_GLASS_MOODBOARD). Shared
 * by the media frame, the graph node cards and the floating node toolbar, so
 * the three surfaces read as one material. The active accents (the selected
 * rim, the running glow) stay at the call sites — only the resting bed and rim
 * live here. No drop shadow: these panes sit on a grid and inside the node
 * clip, where a shadow would be clipped into a line. */
void moodboard_draw_surface(const rctf &rect, float radius);

/** Draw moodboard images */
void mixie_draw_moodboard_images(const bContext *C, View2D *v2d);

/** Draw project-owned freehand annotations in the shared canvas View2D. */
void mixie_draw_moodboard_canvas_annotations(PointerRNA *scene, View2D *v2d);

/** Draw persistent freehand annotations over one moodboard image */
void mixie_draw_moodboard_annotations(PointerRNA *itemptr,
                                      View2D *v2d,
                                      float pos_x,
                                      float pos_y,
                                      float display_width,
                                      float display_height,
                                      float image_scale);

/** Draw image/movie content fitted inside an inference-node result area. */
void mixie_draw_moodboard_media_preview(Image *image, const rctf &bounds);

/** Draw the play/pause affordance centred on a movie frame.
 *
 * Takes the tile's rect rather than a centre so it can size itself through
 * #moodboard_video_play_radius -- screen-size-stable, but never bigger than a
 * fraction of the tile it sits on. */
void mixie_draw_moodboard_video_overlay(View2D *v2d,
                                        const rctf &media_rect,
                                        bool is_playing);

/** Draw moodboard text boxes */
void mixie_draw_moodboard_textboxes(const bContext *C, View2D *v2d);

/**
 * Draw canvas frames: the washed pastel box, its thicker top strip and, on a
 * selected frame, its resize grip. Runs FIRST of every canvas pass -- a
 * translucent wash painted over a card would tint its result.
 */
void mixie_draw_moodboard_frames(const bContext *C, View2D *v2d);

/**
 * Paint each frame's NAME just above its top-left corner. Screen space
 * (plain BLF text, so it takes no uiBlock), drawn late so a member can never
 * cover it. Always drawn, selected or not: a rect cannot say which frame it
 * is, and that is the whole reason a frame carries a name.
 */
void mixie_draw_moodboard_frame_labels(View2D *v2d, ARegion *region, PointerRNA *scene_ptr);

/**
 * The row floating above a SELECTED frame's top-left corner: the pencil that
 * starts the in-place rename and the More menu button -- or, while the rename
 * is running, the name field itself in the row's place
 * (mixie_draw_moodboard_frame_actions.cc).
 */
void moodboard_add_selected_frame_actions(const bContext *C,
                                          ui::Block *block,
                                          View2D *v2d,
                                          ARegion *region,
                                          PointerRNA *scene_ptr);
/** Canvas rect the action row above a frame occupies -- the ONE definition,
 * shared with the frame label so the name never lands under the buttons. */
void moodboard_frame_action_row_rect(const rctf &frame_rect, rctf *r_row);

/* Socket/handle painters and the type palette (mixie_draw_moodboard_graph_sockets.cc).
 * Colors are returned as borrowed float[3] pointers into static palette storage. */
const float *moodboard_socket_type_color(const char *accepted_types);
const float *moodboard_action_output_color(int action_type);
const float *moodboard_media_output_color(const Image *image);
const float *moodboard_mesh_output_color();
void moodboard_draw_socket(
    View2D *v2d, float x, float y, const float color[3], bool connected, bool required, float radius_px);
void moodboard_draw_output_handle(View2D *v2d, float x, float y, const float color[3]);
void moodboard_draw_socket_label(
    View2D *v2d, PointerRNA *socket, float socket_x, float socket_y, float radius_px);
/** Canvas-space width from the same font used by the socket label painter. */
float moodboard_socket_label_width(View2D *v2d, const char *label);

/* Card chrome: canvas-space surfaces/handles and screen-space titles. */
/** The card itself: the shared glass pane, with a brighter rim while selected. */
float moodboard_card_corner_radius(View2D *v2d, PointerRNA *node);
void moodboard_draw_card_background(const rctf &rect, bool selected, float radius);
/** The breathing accent a QUEUED/RUNNING card wears. */
void moodboard_draw_running_glow(const rctf &rect, float radius);
/** Corner resize handles on a SELECTED node card -- the same four squares a
 * selected reference picture wears (see mixie_moodboard_ops_graph_resize.cc). */
void moodboard_draw_node_resize_handles(View2D *v2d, const rctf &rect);
/**
 * The header strip floating above a node card's top edge: the node's name (or,
 * unnamed, its type) on the left and its live queue state on the right. Painted
 * text rather than widgets; reserve space for visible header actions.
 */
/** Screen-space title row; the painter and QA capture share its geometry. */
rctf moodboard_node_title_rect(const rctf &card, float reserved_width = 0.0f);
void moodboard_draw_card_title(const char *title,
                               const rctf &card,
                               bool selected,
                               float reserved_width = 0.0f);
void moodboard_draw_node_header(PointerRNA *node,
                                const rctf &rect,
                                bool selected,
                                float reserved_width = 0.0f);
/** Why the last connection was refused, drawn beside the node it was aimed at.
 * Read-only: the message is posted and cleared from Python. */
void moodboard_draw_graph_notice(PointerRNA *scene_ptr);
/**
 * Give `but` a tooltip whose text is not a compile-time constant.
 *
 * `ui::Button::tip` is a NON-owning StringRef, so a locally built string would
 * dangle the moment the draw function returns — the button outlives it and is
 * what the tooltip is read from, during event handling. These take a copy the
 * button owns and frees.
 */
void moodboard_set_node_tooltip(ui::Button *but, const char *text);
/** Tooltip for one catalog parameter: its name, what it does, and its range. */
/**
 * The controls a node draws inside its own tile: the prompt and Generate, or
 * Cancel while a generation is in flight. Screen space, laid out inside the
 * full card rectangle #moodboard_node_controls_rect returns. The native block
 * clips paint and hit targets independently, preserving spacing during pan.
 * (mixie_draw_moodboard_node_tile_controls.cc)
 */
void moodboard_add_node_tile_controls(ui::Block *block,
                                      PointerRNA *node,
                                      const rcti &tile,
                                      bool generation_running,
                                      bool has_result,
                                      int state,
                                      bool edit_mode,
                                      const char *node_id);
/**
 * The action row floating over a finished card's top edge: an Edit/Cancel-Edit
 * toggle, plus Preview and Export when the result is media.
 *
 * Edit flips the node's `edit_mode`, which folds the settings panel and the
 * in-tile prompt in and out — a presentation flag only, so the node keeps its
 * state, its result and its error either way. Preview and Export are scoped to
 * this node's own result rather than the selection.
 */
float moodboard_node_card_actions_width(bool has_media);
void moodboard_add_node_card_actions(ui::Block *block,
                                     const rcti &card,
                                     bool edit_mode,
                                     bool has_media_result,
                                     const char *node_id);
/**
 * The action row floating above a selected reference image or movie: Rename,
 * Preview and Export, on the same line and in the same order as a finished
 * card's Edit / Preview / Export (mixie_draw_moodboard_media_actions.cc).
 * Every button is scoped to the tile it sits on through the media's graph id.
 */
void moodboard_add_media_card_actions(ui::Block *block,
                                      const rcti &media_region,
                                      const char *media_id);
/** One row per selected standalone media, added to the canvas block -- or,
 * for the media being renamed, the in-place name field in the row's place. */
void moodboard_add_selected_media_actions(const bContext *C,
                                          ui::Block *block,
                                          View2D *v2d,
                                          ARegion *region,
                                          PointerRNA *scene_ptr,
                                          const MoodboardGraphCache *cache);
/** Screen-space rect the row above `media_rect` occupies -- the ONE definition,
 * shared with the selected-media label so the name never lands under it. */
void moodboard_media_action_row_rect(const rctf &media_rect, rctf *r_row);

/* Shared by the node-UI toolbar and the selected-media name
 * (mixie_draw_moodboard_node_ui.cc / mixie_draw_moodboard_media_labels.cc). */
bool moodboard_view_rect_to_region(View2D *v2d,
                                   ARegion *region,
                                   const rctf &view_rect,
                                   rcti *r_region_rect);
/** Paint each selected standalone media's own name just above it. Plain BLF
 * text, no widgets and no background of its own -- it takes no #ui::Block. The
 * context is what bounds it to the painted canvas, which in the Zen drawer is
 * narrower than the region. */
void mixie_draw_moodboard_selected_media_labels(const bContext *C,
                                                View2D *v2d,
                                                ARegion *region,
                                                PointerRNA *scene_ptr,
                                                const MoodboardGraphCache *cache);

/* The graph passes share ONE per-frame #MoodboardGraphCache built by
 * #mixie_draw_moodboard_mode — each pass resolving media rects on its own
 * re-acquired every image's ImBuf several times per redraw. */

/** Draw persistent graph links behind canvas nodes. */
void mixie_draw_moodboard_links(const bContext *C,
                                View2D *v2d,
                                const MoodboardGraphCache *cache);

/** Draw inference blocks and generated 3D asset cards. */
void mixie_draw_moodboard_graph_nodes(const bContext *C,
                                      View2D *v2d,
                                      const MoodboardGraphCache *cache);

/** Draw editable catalog-backed controls directly inside inference nodes. */
void mixie_draw_moodboard_graph_controls(const bContext *C,
                                         View2D *v2d,
                                         const MoodboardGraphCache *cache);

/** Draw edit tool overlay (crop/mask/lasso) */
void mixie_draw_edit_tool_overlay(const bContext *C, View2D *v2d);

/** \} */

}  // namespace blender::ed::mixie
