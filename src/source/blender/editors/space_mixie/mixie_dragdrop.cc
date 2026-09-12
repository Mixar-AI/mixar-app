/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 */

#include "DNA_space_types.h"

#include "BKE_context.hh"
#include "BKE_screen.hh"

#include "ED_screen.hh"

#include "RNA_access.hh"

#include "UI_view2d.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_intern.hh"
#include "mixie_moodboard_ops_common.hh"

#include <string>
#include <vector>
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Moodboard Media Drop Poll
 * \{ */

static bool moodboard_image_drop_poll(bContext *C, wmDrag *drag, const wmEvent * /*event*/)
{
  const ScrArea *area = CTX_wm_area(C);
  const ARegion *region = CTX_wm_region(C);
  const WorkSpace *workspace = CTX_wm_workspace(C);
  /* A reference dropped into Zen's viewport reveals the board, including
   * when the drawer is closed or still sliding. Other workspaces keep their
   * native image/background drops. */
  const bool zen_reference = area && area->spacetype == SPACE_VIEW3D && region &&
                             ELEM(region->regiontype, RGN_TYPE_WINDOW, RGN_TYPE_TOOL_PROPS) &&
                             workspace && STREQ(workspace->id.name + 2, "Zen Mode");
  if (!zen_reference && !ed::mixie::moodboard_poll(C)) {
    return false;
  }

  /* Accept image and movie files, including mixed multi-file drops. */
  if (drag->type == WM_DRAG_PATH) {
    if (WM_drag_has_path_file_type(drag, FILE_TYPE_IMAGE) ||
        WM_drag_has_path_file_type(drag, FILE_TYPE_MOVIE))
    {
      return true;
    }
  }

  /* Accept Image ID drags */
  if (WM_drag_is_ID_type(drag, ID_IM)) {
    return true;
  }

  return false;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Moodboard Media Drop Copy
 * \{ */

static void moodboard_image_drop_copy(bContext *C, wmDrag *drag, wmDropBox *drop)
{
  /* Clear stale properties from any previous drop so only the current
   * drop's data is present when the operator executes. */
  RNA_struct_property_unset(drop->ptr, "filepath");
  RNA_struct_property_unset(drop->ptr, "image_name");
  RNA_struct_property_unset(drop->ptr, "multi_filepaths");
  RNA_boolean_set(drop->ptr, "from_drop", false);
  RNA_boolean_set(drop->ptr, "center_on_drop", false);

  /* Get View2D coordinates at drop position */
  ARegion *region = CTX_wm_region(C);
  if (!region) {
    return;
  }

  ScrArea *area = CTX_wm_area(C);
  const bool reveal = area->spacetype == SPACE_VIEW3D &&
                      !ed::mixie::moodboard_zen_drawer_active(C);
  if (area->spacetype == SPACE_VIEW3D) {
    region = BKE_area_find_region_type(area, RGN_TYPE_TOOL_PROPS);
    if (!region) {
      return;
    }
  }
  View2D *v2d = &region->v2d;
  wmWindow *win = CTX_wm_window(C);

  /* Get window-absolute mouse coordinates */
  int xy[2];
  xy[0] = win->runtime->eventstate->xy[0];
  xy[1] = win->runtime->eventstate->xy[1];

  /* Convert to region-local coordinates */
  int mval[2];
  mval[0] = xy[0] - region->winrct.xmin;
  mval[1] = xy[1] - region->winrct.ymin;

  /* Convert region coordinates to View2D canvas coordinates */
  float pos_x, pos_y;
  ui::view2d_region_to_view(v2d, mval[0], mval[1], &pos_x, &pos_y);
  if (reveal) {
    /* The cursor is in the viewport, not on the canvas. Land in the drawer's
     * current view, even if the user previously panned far from the origin. */
    pos_x = BLI_rctf_cent_x(&v2d->cur);
    pos_y = BLI_rctf_cent_y(&v2d->cur);
    RNA_boolean_set(drop->ptr, "center_on_drop", true);
  }

  /* Set drop position in operator properties */
  RNA_float_set(drop->ptr, "position_x", pos_x);
  RNA_float_set(drop->ptr, "position_y", pos_y);

  /* Handle file path drops */
  if (drag->type == WM_DRAG_PATH) {
    blender::Span<std::string> paths = WM_drag_get_paths(drag);
    
    if (paths.size() > 1) {
      std::string joined_paths;
      for (const std::string &path : paths) {
        if (!joined_paths.empty()) {
          joined_paths += "|";
        }
        joined_paths += path;
      }
      RNA_string_set(drop->ptr, "multi_filepaths", joined_paths.c_str());
      RNA_boolean_set(drop->ptr, "from_drop", true);
    }
    else {
      const char *path = WM_drag_get_single_path(drag);
      if (path) {
        RNA_string_set(drop->ptr, "filepath", path);
        RNA_boolean_set(drop->ptr, "from_drop", true);
      }
    }
  }
  /* Handle Image ID drops */
  else if (drag->type == WM_DRAG_ID) {
    wmDragID *drag_id = static_cast<wmDragID *>(drag->ids.first);
    if (drag_id && drag_id->id && GS(drag_id->id->name) == ID_IM) {
      Image *image = reinterpret_cast<Image *>(drag_id->id);
      RNA_string_set(drop->ptr, "image_name", image->id.name + 2);
      RNA_boolean_set(drop->ptr, "from_drop", true);
    }
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Dropbox Registration
 * \{ */

void mixie_dropboxes()
{
  ListBaseT<wmDropBox> *lb = WM_dropboxmap_find("Mixie", SPACE_MIXIE, RGN_TYPE_WINDOW);

  WM_dropbox_add(lb,
                 "MIXIE_OT_moodboard_drop_image",
                 moodboard_image_drop_poll,
                 moodboard_image_drop_copy,
                 nullptr,  /* cancel */
                 nullptr); /* tooltip */
}

/** \} */
}  // namespace blender
