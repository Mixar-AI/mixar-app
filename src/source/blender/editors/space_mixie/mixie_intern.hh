/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 */

#pragma once

#include "RNA_types.hh"

/* internal exports only */

struct ARegion;
struct bContext;
struct Image;
struct PointerRNA;
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
#define MOODBOARD_IMAGE_MIN_SCALE 0.1f
#define MOODBOARD_IMAGE_MAX_SCALE 50.0f
#define MOODBOARD_IMAGE_SCALE_DELTA 0.1f
#define MOODBOARD_MAX_SELECTED_IMAGES 256
#define MOODBOARD_VIDEO_PLAY_RADIUS_PX 28.0f

/* Moodboard Interaction Constants */
#define MOODBOARD_HANDLE_TOLERANCE_PX 16.0f
#define MOODBOARD_DRAG_THRESHOLD_PX 5.0f

/* Moodboard Grid Constants */
#define MOODBOARD_GRID_SMALL_SPACING 10.0f
#define MOODBOARD_GRID_MAJOR_SPACING 100.0f
#define MOODBOARD_GRID_MAJOR_FREQUENCY 10

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

/** Whether the moodboard item at \a index references a movie datablock. */
bool moodboard_item_is_video(PointerRNA *scene_ptr, int index);

/** Open a fitted Image Editor window for a moodboard movie. */
bool moodboard_open_video_preview(bContext *C,
                                  PointerRNA *scene_ptr,
                                  int index,
                                  ReportList *reports);

/** Deselect all moodboard items (images and textboxes) */
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
void MIXIE_OT_moodboard_zoom(wmOperatorType *ot);
void MIXIE_OT_moodboard_ensure_visible(wmOperatorType *ot);
void MIXIE_OT_moodboard_box_select(wmOperatorType *ot);
void MIXIE_OT_moodboard_generate_box_mask(wmOperatorType *ot);
void MIXIE_OT_moodboard_generate_lasso_mask(wmOperatorType *ot);
void MIXIE_OT_moodboard_crop_image(wmOperatorType *ot);

/** \} */
