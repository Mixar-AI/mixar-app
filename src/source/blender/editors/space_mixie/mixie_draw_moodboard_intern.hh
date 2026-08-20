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

namespace blender::ed::mixie {

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

/** Draw the shared neutral node frame behind imported image/movie content. */
void mixie_draw_moodboard_media_frame(float x, float y, float w, float h, bool selected);

/** Draw moodboard images */
void mixie_draw_moodboard_images(const bContext *C, View2D *v2d);

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

/** Draw the screen-size-stable play/pause affordance over a movie frame. */
void mixie_draw_moodboard_video_overlay(
    View2D *v2d, float center_x, float center_y, bool is_playing);

/** Draw moodboard text boxes */
void mixie_draw_moodboard_textboxes(const bContext *C, View2D *v2d);

/** Draw moodboard groups */
void mixie_draw_moodboard_groups(const bContext *C, View2D *v2d);

/** Draw persistent graph links behind canvas nodes. */
void mixie_draw_moodboard_links(const bContext *C, View2D *v2d);

/** Draw inference blocks and generated 3D asset cards. */
void mixie_draw_moodboard_graph_nodes(const bContext *C, View2D *v2d);

/** Draw editable catalog-backed controls directly inside inference nodes. */
void mixie_draw_moodboard_graph_controls(const bContext *C, View2D *v2d);

/** Draw edit tool overlay (crop/mask/lasso) */
void mixie_draw_edit_tool_overlay(const bContext *C, View2D *v2d);

/** \} */

}  // namespace blender::ed::mixie
