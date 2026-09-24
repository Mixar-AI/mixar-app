/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup spapi
 */

#include "DNA_screen_types.h"
#include "DNA_space_enums.h"

#include "RNA_access.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixar_file_drop.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

static bool mixar_file_drop_poll(bContext * /*C*/, wmDrag *drag, const wmEvent * /*event*/)
{
  return drag->type == WM_DRAG_PATH && WM_drag_get_path_file_type(drag) == FILE_TYPE_MIXAR;
}

static void mixar_file_drop_copy(bContext * /*C*/, wmDrag *drag, wmDropBox *drop)
{
  RNA_string_set(drop->ptr, "filepath", WM_drag_get_single_path(drag));
}

void ED_dropboxes_mixar_file()
{
  ListBaseT<wmDropBox> *dropboxes = WM_dropboxmap_find("Window", SPACE_EMPTY, RGN_TYPE_WINDOW);
  WM_dropbox_add(dropboxes,
                 "WM_OT_drop_blend_file",
                 mixar_file_drop_poll,
                 mixar_file_drop_copy,
                 nullptr,
                 nullptr);
}

}  // namespace blender
