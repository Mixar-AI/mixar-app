/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Cinema Mode: the "My Cameras" card in the right column.
 *
 * The list is the SCENE's cameras, not Director's shots. A shot-based list
 * could only show cameras Director had already adopted, so the scene's own
 * default camera — and every camera imported, generated or added from the
 * outliner — was missing until something happened to create a shot for it.
 * Reading the scene each draw also means a camera deleted anywhere (outliner,
 * viewport, a script) simply stops being drawn, and the live row follows
 * `scene->camera` however it was changed.
 *
 * Takes are not rows: several shots may direct one camera, and
 * `mixar.director_pick_camera` switches to the newest take of the camera
 * clicked (or mints a shot for one that has none). "My Cameras" names cameras.
 *
 * Painting only; every control is an ordinary uiBut over the painted pixels.
 */

#include <algorithm>
#include <cstring>

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_vector.hh"

#include "BKE_context.hh"
#include "BKE_wm_runtime.hh"

#include "DNA_object_types.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_resources.hh"

#include "ED_screen.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "../interface/interface_mixar_profile_card.hh"

#include "view3d_director.hh"
#include "view3d_director_cinema.hh"
#include "view3d_director_overlay_intern.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/* Design px, inside the card. The caption used to sit at 13 and the rows at
 * 11 against a 10 right edge, so nothing in the card lined up with anything
 * else; #CINEMA_CARD_PAD is the one inset every card uses now. */
constexpr float ADD_CHIP_W = 96.0f;
constexpr float ADD_CHIP_H = 22.0f;
/** Card top -> first row's top. */
constexpr float FIRST_ROW_OFFSET = 66.0f;
/** Square delete affordance at a row's right edge. */
constexpr float DELETE_SIZE = 18.0f;

/**
 * In-place editable text over a name the surface painted itself.
 *
 * A Text button under Emboss::None is NOT interactive for plain hover or
 * clicks (`button_is_interactive_ex`): those fall through to the operator
 * button created before it on the same rect. A label edit (Ctrl held)
 * reaches it directly, and the operator button — tagged with
 * #UI_mixar_button_double_click_edits_label — hands it a double-click or
 * Ctrl+click the way a UI-list row does; the stock text editor then runs
 * (Enter commits, Esc cancels). Idle it paints nothing; tagged #Field so
 * the card painter lays the row chip under Blender's edit drawing.
 */
ui::Button *cinema_text_field(ui::Block *block,
                              PointerRNA *ptr,
                              const char *prop_name,
                              const rctf &rect,
                              const char *tooltip)
{
  ui::block_emboss_set(block, blender::ui::EmbossType::None);
  ui::Button *but = ui::uiDefButR(block,
                                  ui::ButtonType::Text,
                                  "",
                                  int(rect.xmin),
                                  int(rect.ymin),
                                  short(BLI_rctf_size_x(&rect)),
                                  short(BLI_rctf_size_y(&rect)),
                                  ptr,
                                  prop_name,
                                  0,
                                  0,
                                  0,
                                  tooltip);
  ui::block_emboss_set(block, blender::ui::EmbossType::Emboss);
  if (but != nullptr) {
    /* Contract with the tag: a Text button's `hardmax` IS its edit-buffer
     * size (`button_string_get_maxncpy`), so the tag must leave it alone for
     * `ButtonType::Text` and the painter must key #Field on the type, the way
     * Option is keyed on `ButtonType::Row`. A tag that wrote the kind there
     * would truncate every rename to five characters. */
    ui::UI_mixar_cinema_row_tag(but, ui::MixarCinemaRowKind::Field);
  }
  return but;
}

/**
 * The scene's camera objects, in the order the outliner shows them.
 *
 * Read through RNA's `Scene.objects` rather than a DNA walk: it is exactly
 * the collection the outliner lists, and it is the same bridge the rest of
 * this surface reads Director state through. Sorted by name so a row does
 * not move under the cursor when an unrelated object is added.
 */
void collect_scene_cameras(Scene *scene, blender::Vector<Object *> *r_cameras)
{
  if (scene == nullptr) {
    return;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *objects_prop = RNA_struct_find_property(&scene_ptr, "objects");
  if (objects_prop == nullptr) {
    return;
  }
  RNA_PROP_BEGIN (&scene_ptr, object_ptr, objects_prop) {
    Object *object = static_cast<Object *>(object_ptr.data);
    if (object != nullptr && object->type == OB_CAMERA) {
      r_cameras->append(object);
    }
  }
  RNA_PROP_END;
  std::sort(r_cameras->begin(), r_cameras->end(), [](const Object *a, const Object *b) {
    return BLI_strcasecmp(a->id.name + 2, b->id.name + 2) < 0;
  });
}

/**
 * Scroll state for the card, published by the painter and read by the wheel
 * operator's poll. One Director viewport draws the surface at a time (the
 * aerial map's buffers are a file-static for the same reason), so one set of
 * statics is enough — and `region` is recorded so a stale rect from another
 * region can never answer a poll.
 */
struct CameraListScroll {
  const ARegion *region = nullptr;
  rctf rect = {};
  int count = 0;
  int visible = 0;
  int offset = 0;
  /** Row pitch in REGION px, published by the painter so a trackpad gesture
   * can turn its pixels into rows without re-deriving the layout. */
  float row_pitch = 0.0f;
  /** The live camera as of the last draw. Published so a scroll can adopt it
   * WITHOUT the painter having to run first — see #followed. */
  const Object *live = nullptr;
  /** The live camera the window currently belongs to. The painter re-snaps
   * whenever this stops matching #live, so anything that legitimately owns
   * the window has to claim the live camera rather than clear this. */
  const Object *followed = nullptr;
};

CameraListScroll g_scroll;

int scroll_max(const CameraListScroll &scroll)
{
  return std::max(0, scroll.count - scroll.visible);
}

}  // namespace

bool cinema_camera_list_contains(const ARegion *region, const int x, const int y)
{
  return g_scroll.region == region && scroll_max(g_scroll) > 0 &&
         BLI_rctf_isect_pt(&g_scroll.rect, float(x), float(y));
}

float cinema_camera_list_row_pitch()
{
  return g_scroll.row_pitch;
}

bool cinema_camera_list_scroll(const int delta)
{
  const int maximum = scroll_max(g_scroll);
  const int next = std::clamp(g_scroll.offset + delta, 0, maximum);
  if (next == g_scroll.offset) {
    return false;
  }
  g_scroll.offset = next;
  /* A deliberate scroll owns the window until the live camera CHANGES, and
   * that is spelled "adopt the camera it is live on", never "forget which
   * camera it is on".
   *
   * This is why the list would not scroll. Clearing `followed` left it null
   * while a camera was live, so the painter's `followed != live` re-snap
   * fired on the very next draw — the one this scroll itself tags — and put
   * the window straight back around the highlighted row. Every wheel step
   * was undone before a frame of it could be seen, which reads exactly like
   * a wheel that does nothing. */
  g_scroll.followed = g_scroll.live;
  return true;
}

void cinema_camera_list_release(const ARegion *region)
{
  if (g_scroll.region == region) {
    g_scroll = CameraListScroll{};
  }
}

void cinema_draw_camera_list(ui::Block *block,
                             const bContext *C,
                             const ARegion *region,
                             const DirectorViewState &state,
                             const rctf &card)
{
  const float u = cinema_unit();
  MIXAR_THEME_LOAD(label_col, CinemaRowCaption);
  MIXAR_THEME_LOAD(value_col, CinemaRowTextOn);
  MIXAR_THEME_LOAD(dim_col, CinemaRowTextDisabled);
  Scene *scene = CTX_data_scene(const_cast<bContext *>(C));

  cinema_glass_panel(card, CINEMA_PANEL_RADIUS * u);
  cinema_text_left("My Cameras",
                   card.xmin + CINEMA_CARD_PAD * u,
                   card.ymax - 22.0f * u,
                   CINEMA_FONT_LABEL * u,
                   label_col);

  /* Add Camera chip. */
  rctf add;
  add.xmax = card.xmax - CINEMA_CARD_PAD * u;
  add.xmin = add.xmax - ADD_CHIP_W * u;
  add.ymax = card.ymax - 12.0f * u;
  add.ymin = add.ymax - ADD_CHIP_H * u;
  MIXAR_THEME_LOAD(add_top, CinemaRowTop);
  const float add_bottom[4] = {0.192f, 0.192f, 0.192f, 1.0f}; /* #313131 */
  cinema_panel(add, BLI_rctf_size_y(&add) * 0.5f, add_top, add_bottom);
  cinema_text_center("+ Add Camera",
                     BLI_rctf_cent_x(&add),
                     BLI_rctf_cent_y(&add),
                     11.0f * u,
                     value_col);
  /* With nothing directed yet this is the session's entry point, and it must
   * stay `director_start`: that one adopts a camera the scene already has,
   * where `new_shot` would always mint another one beside it. */
  cinema_qa_record(region, add, "director_add_camera", "add", -1);
  cinema_op_button(block,
                   state.has_shot ? "MIXAR_OT_director_new_shot" : "MIXAR_OT_director_start",
                   add,
                   state.has_shot ? "Create a new shot camera from this view" :
                                    "Direct the active scene camera from the viewport");

  blender::Vector<Object *> cameras;
  collect_scene_cameras(scene, &cameras);
  if (cameras.is_empty()) {
    cinema_camera_list_release(region);
    cinema_text_center("No cameras yet",
                       BLI_rctf_cent_x(&card),
                       BLI_rctf_cent_y(&card) - 10.0f * u,
                       CINEMA_FONT_VALUE * u,
                       dim_col);
    return;
  }

  /* The live row is the scene's active camera, so the highlight follows a
   * change made anywhere — the outliner, a shot switch, a script. */
  const Object *live = scene ? scene->camera : nullptr;
  int active_index = 0;
  for (const int index : cameras.index_range()) {
    if (cameras[index] == live) {
      active_index = index;
    }
  }

  const float row_h = cinema_list_row_h() * u;
  const int count = int(cameras.size());
  const int visible_rows = std::min(count, int(CINEMA_LIST_MAX_ROWS));

  /* The window follows the LIVE camera whenever it changes — a highlight the
   * card cannot show is worse than losing a scroll position — and otherwise
   * stays exactly where the user scrolled it. */
  g_scroll.region = region;
  g_scroll.count = count;
  g_scroll.visible = visible_rows;
  g_scroll.live = live;
  if (g_scroll.followed != live) {
    g_scroll.offset = cinema_list_window_start(count, active_index);
    g_scroll.followed = live;
  }
  g_scroll.offset = std::clamp(g_scroll.offset, 0, scroll_max(g_scroll));
  g_scroll.row_pitch = CINEMA_LIST_PITCH * u;
  const int first_row = g_scroll.offset;
  const float first_row_top = card.ymax - FIRST_ROW_OFFSET * u;

  /* The scrollable band is the rows, not the whole card: a wheel over the
   * "My Cameras" caption or the Add Camera chip keeps its viewport meaning. */
  g_scroll.rect = {card.xmin,
                   card.xmax,
                   first_row_top - CINEMA_LIST_PITCH * float(visible_rows) * u,
                   first_row_top};

  for (int slot = 0; slot < visible_rows; slot++) {
    const int index = first_row + slot;
    if (index >= int(cameras.size())) {
      break;
    }
    Object *camera = cameras[index];
    const char *name = camera->id.name + 2;
    const bool active = camera == live;

    rctf row;
    row.xmin = card.xmin + CINEMA_CARD_PAD * u;
    row.xmax = card.xmax - CINEMA_CARD_PAD * u;
    row.ymax = first_row_top - CINEMA_LIST_PITCH * float(slot) * u;
    row.ymin = row.ymax - row_h;
    if (active) {
      MIXAR_THEME_LOAD(top, CinemaRowTop);
      MIXAR_THEME_LOAD(bottom, CinemaRowBottom);
      cinema_panel(row, CINEMA_ROW_RADIUS * u, top, bottom);
    }
    /* The row's own hit area stops short of the delete chip so the two never
     * share a band: `ui_but_find_mouse_over_ex` walks a block BACKWARDS, and
     * the later-created button would otherwise take the row's clicks. */
    const rctf remove = {row.xmax - (DELETE_SIZE + 4.0f) * u,
                         row.xmax - 4.0f * u,
                         BLI_rctf_cent_y(&row) - DELETE_SIZE * u * 0.5f,
                         BLI_rctf_cent_y(&row) + DELETE_SIZE * u * 0.5f};
    rctf select = row;
    select.xmax = remove.xmin - 2.0f * u;

    /* Measured against the room the delete chip leaves: an unmeasured name
     * ran out under that chip and off the card, and camera names are the one
     * string on this surface a user types themselves. */
    const float name_x = row.xmin + 12.0f * u;
    cinema_text_left_fitted(name,
                            name_x,
                            BLI_rctf_cent_y(&row),
                            CINEMA_FONT_VALUE * u,
                            select.xmax - name_x,
                            active ? value_col : dim_col);

    cinema_qa_record(region, select, "director_camera", name, index);
    ui::Button *but = cinema_op_button(
        block, "MIXAR_OT_director_pick_camera", select, "Direct this camera");
    if (but != nullptr) {
      RNA_string_set(ui::button_operator_ptr_ensure(but), "camera_name", name);
      ui::UI_mixar_button_double_click_edits_label(but);
    }
    /* The rename field is created AFTER the operator button on the same
     * rect: hit-testing walks a block backwards, so it is asked first — and
     * declines everything but a label edit, leaving the click to the
     * operator, which hands back double-click and Ctrl+click through its
     * tag. Renaming an ID through RNA keeps names unique on its own. */
    PointerRNA camera_ptr = RNA_id_pointer_create(&camera->id);
    cinema_text_field(
        block, &camera_ptr, "name", select, "Rename this camera: double-click or Ctrl+click");

    /* Created LAST and on its own rect, so it is asked before the row and
     * answers only its own pixels. The operator confirms before deleting. */
    cinema_qa_record(region, remove, "director_camera_delete", name, index);
    ui::Button *remove_but = cinema_icon_button(block,
                                                "MIXAR_OT_director_delete_camera",
                                                ICON_X,
                                                remove,
                                                "Delete this camera and its shots");
    if (remove_but != nullptr) {
      RNA_string_set(ui::button_operator_ptr_ensure(remove_but), "camera_name", name);
    }
  }

  /* A hairline track on the card's right edge: without it there is nothing to
   * say the list continues past the fourth row. */
  const int maximum = scroll_max(g_scroll);
  if (maximum > 0) {
    const float track_col[4] = {1.0f, 1.0f, 1.0f, 0.08f};
    const float thumb_col[4] = {1.0f, 1.0f, 1.0f, 0.28f};
    const float width = 3.0f * u;
    const rctf track = {g_scroll.rect.xmax - (CINEMA_CARD_PAD - 8.0f) * u - width,
                        g_scroll.rect.xmax - (CINEMA_CARD_PAD - 8.0f) * u,
                        g_scroll.rect.ymin + 2.0f * u,
                        g_scroll.rect.ymax - 2.0f * u};
    cinema_fill(track, width * 0.5f, track_col);
    const float span = BLI_rctf_size_y(&track);
    const float thumb_h = std::max(width * 2.0f, span * float(visible_rows) / float(count));
    const float travel = (span - thumb_h) * float(first_row) / float(maximum);
    const rctf thumb = {
        track.xmin, track.xmax, track.ymax - thumb_h - travel, track.ymax - travel};
    cinema_fill(thumb, width * 0.5f, thumb_col);
  }
}

/** \} */

}  // namespace blender
