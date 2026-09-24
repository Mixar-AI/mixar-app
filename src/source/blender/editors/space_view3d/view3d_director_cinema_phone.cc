/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Cinema Mode: the phone hand-off — the top strip's button and the pairing
 * card it raises over the stage.
 *
 * This IS the Virtual Camera's UI. The feature shipped behind a View3D
 * sidebar tab, which is the one place a director is never looking: Cinema
 * Mode is a full-surface shell with a designed "Drive camera from your
 * phone" button, and that button is where handing the camera to a phone
 * belongs.
 *
 * Presentation only. The server, the pairing token and the camera pump are
 * Python (`modules/virtual_camera/`), reached through the
 * `mixar.virtual_camera_*` operators; their state arrives on the
 * WindowManager mirror that `core/wm_mirror.py` is the sole writer of. The
 * mirror is read, never written, here — a draw callback must not touch RNA
 * values.
 *
 * The QR arrives as its MODULES, not as an image: row-major `'0'`/`'1'`
 * painted with the surface's own primitives. No image datablock to leak into
 * a `.blend`, no preview collection to rebuild mid-draw, no file read on the
 * draw path — and it stays crisp at whatever size the stage allows.
 */

#include <algorithm>
#include <cstring>

#include "BLI_rect.h"

#include "BKE_context.hh"

#include "DNA_screen_types.h"
#include "DNA_windowmanager_types.h"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_resources.hh"

#include "view3d_director.hh"
#include "view3d_director_cinema.hh"
#include "view3d_director_cinema_phone.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/** Modules per side of the largest QR the encoder emits (`MAX_VERSION` 10). */
constexpr int PHONE_QR_MAX_SIDE = 57;
/** Quiet zone, in modules, around the code. Scanners need one; 3 reads well. */
constexpr int PHONE_QR_QUIET = 3;

/* Card metrics, design px (see #cinema_unit). */
constexpr float PHONE_CARD_W = 306.0f;
constexpr float PHONE_CARD_PAD = 18.0f;
constexpr float PHONE_QR_EDGE = 216.0f;
constexpr float PHONE_TITLE_H = 22.0f;
constexpr float PHONE_LINE_H = 17.0f;
constexpr float PHONE_ROW_H = 30.0f;
constexpr float PHONE_GAP = 9.0f;
constexpr float PHONE_CARD_RADIUS = 16.0f;

/** Everything the card paints, copied out of the mirror in one pass. */
struct PhoneState {
  bool running = false;
  bool connected = false;
  bool tls = false;
  int qr_side = 0;
  char url[512] = {};
  char notice[256] = {};
  char qr[PHONE_QR_MAX_SIDE * PHONE_QR_MAX_SIDE + 1] = {};
};

bool mirror_bool(PointerRNA *wm_ptr, const char *name)
{
  PropertyRNA *prop = RNA_struct_find_property(wm_ptr, name);
  return prop != nullptr && RNA_property_boolean_get(wm_ptr, prop);
}

int mirror_int(PointerRNA *wm_ptr, const char *name)
{
  PropertyRNA *prop = RNA_struct_find_property(wm_ptr, name);
  return prop != nullptr ? RNA_property_int_get(wm_ptr, prop) : 0;
}

/**
 * Copy a mirror string into \a dst, or leave it empty.
 *
 * Never allocates: a value that does not fit is dropped rather than
 * truncated, because half a pairing URL or half a QR is worse than none —
 * the card falls back to the text link, or to no code at all.
 */
void mirror_string(PointerRNA *wm_ptr, const char *name, char *dst, const int dst_maxncpy)
{
  dst[0] = '\0';
  PropertyRNA *prop = RNA_struct_find_property(wm_ptr, name);
  if (prop == nullptr) {
    return;
  }
  if (RNA_property_string_length(wm_ptr, prop) >= dst_maxncpy) {
    return;
  }
  RNA_property_string_get(wm_ptr, prop, dst);
}

bool wm_pointer(const bContext *C, PointerRNA *r_ptr)
{
  wmWindowManager *wm = CTX_wm_manager(const_cast<bContext *>(C));
  if (wm == nullptr) {
    return false;
  }
  *r_ptr = RNA_id_pointer_create(&wm->id);
  return true;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name QR
 * \{ */

/**
 * Paint the code: a light bed with its quiet zone, then the dark modules.
 *
 * Consecutive dark modules in a row are merged into ONE rect, which turns a
 * 1369-quad code into a couple of hundred — the card is transient, but it
 * sits over a live viewport and must not cost it a frame.
 */
void paint_qr(const PhoneState &state, const rctf &area)
{
  const int side = state.qr_side;
  if (side <= 0 || int(strlen(state.qr)) < side * side) {
    return;
  }
  const float span = std::min(BLI_rctf_size_x(&area), BLI_rctf_size_y(&area));
  const float module = span / float(side + 2 * PHONE_QR_QUIET);
  const float bed_edge = module * float(side + 2 * PHONE_QR_QUIET);
  const float bed_x = BLI_rctf_cent_x(&area) - bed_edge * 0.5f;
  const float bed_y = BLI_rctf_cent_y(&area) - bed_edge * 0.5f;
  const rctf bed = {bed_x, bed_x + bed_edge, bed_y, bed_y + bed_edge};
  const float light[4] = {0.973f, 0.973f, 0.973f, 1.0f};
  const float dark[4] = {0.063f, 0.071f, 0.086f, 1.0f};
  cinema_fill(bed, 6.0f * cinema_unit(), light);

  const float left = bed_x + module * float(PHONE_QR_QUIET);
  /* Matrix rows run top-down; the region's y runs up. */
  const float top = bed_y + bed_edge - module * float(PHONE_QR_QUIET);
  for (int row = 0; row < side; row++) {
    const char *cells = state.qr + row * side;
    const float y1 = top - module * float(row);
    const float y0 = y1 - module;
    int column = 0;
    while (column < side) {
      if (cells[column] != '1') {
        column++;
        continue;
      }
      const int run_start = column;
      while (column < side && cells[column] == '1') {
        column++;
      }
      const rctf cell = {left + module * float(run_start), left + module * float(column), y0, y1};
      cinema_fill(cell, 0.0f, dark);
    }
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Card rows
 * \{ */

/**
 * One centred line, shrunk to fit \a width.
 *
 * The surface's text painters do not clip, and a pairing URL
 * (`https://192.168.1.42:8143/?t=<32 hex>`) is wider than the card at the
 * caption size — unshrunk it would run out over the stage.
 */
void text_center_fitted(
    const char *text, const float cx, const float cy, const float size, const float width,
    const float col[4])
{
  float fitted = size;
  const float natural = cinema_text_width(text, size);
  if (natural > width && natural > 0.0f) {
    fitted = std::max(size * (width / natural), size * 0.7f);
  }
  cinema_text_center(text, cx, cy, fitted, col);
}

/** A labelled action chip: painted row, invisible operator button over it. */
void action_chip(ui::Block *block,
                 const ARegion *region,
                 const rctf &rect,
                 const char *operator_id,
                 const char *label,
                 const char *tooltip,
                 const char *qa_value)
{
  const float u = cinema_unit();
  MIXAR_THEME_LOAD(top, CinemaRowTop);
  MIXAR_THEME_LOAD(bottom, CinemaRowBottom);
  cinema_panel(rect, CINEMA_ROW_RADIUS * u, top, bottom);
  MIXAR_THEME_LOAD(value_col, CinemaRowTextOn);
  cinema_text_center(
      label, BLI_rctf_cent_x(&rect), BLI_rctf_cent_y(&rect), CINEMA_FONT_VALUE * u, value_col);
  cinema_op_button(block, operator_id, rect, tooltip);
  cinema_qa_record(region, rect, "director_phone_card", qa_value, -1);
}

/** \} */

}  // namespace

/* -------------------------------------------------------------------- */
/** \name Public surface
 * \{ */

CinemaPhoneStatus cinema_phone_status(const bContext *C)
{
  CinemaPhoneStatus status;
  PointerRNA wm_ptr = {};
  if (!wm_pointer(C, &wm_ptr)) {
    return status;
  }
  status.running = mirror_bool(&wm_ptr, "mixar_virtual_camera_running");
  status.connected = mirror_bool(&wm_ptr, "mixar_virtual_camera_connected");
  return status;
}

void cinema_draw_phone_button(ui::Block *block,
                              const bContext *C,
                              const ARegion *region,
                              const rctf &rect)
{
  const float u = cinema_unit();
  const CinemaPhoneStatus status = cinema_phone_status(C);

  /* Three states, three things the click means. A button that reads "Drive
   * camera from your phone" while a phone is already driving would hand
   * control back without saying so. */
  const char *label = status.connected ? "Phone connected" :
                      status.running   ? "Waiting for your phone" :
                                         "Drive camera from your phone";
  const char *tooltip = status.connected ?
                            "Hand the camera back and disconnect the phone" :
                        status.running ?
                            "Stop waiting and close the pairing code" :
                            "Pair a phone over Wi-Fi and drive this camera with it";

  if (status.connected) {
    MIXAR_THEME_LOAD(on, Primary);
    cinema_fill(rect, CINEMA_ROW_RADIUS * u, on);
  }
  else {
    MIXAR_THEME_LOAD(bg, CinemaPhone);
    cinema_fill(rect, CINEMA_ROW_RADIUS * u, bg);
  }

  const float text[4] = {0.957f, 0.957f, 0.957f, 0.9f};
  const float glyph_w = 11.0f * u;
  const float glyph_gap = 9.0f * u;
  const float label_w = cinema_text_width(label, CINEMA_FONT_VALUE * u);
  /* The label gives way to the glyph alone when the column cannot hold it. */
  const bool compact = glyph_w + glyph_gap + label_w > BLI_rctf_size_x(&rect) - 8.0f * u;
  const float pair_w = compact ? glyph_w : glyph_w + glyph_gap + label_w;
  const float x0 = BLI_rctf_cent_x(&rect) - pair_w * 0.5f;
  const float cy = BLI_rctf_cent_y(&rect);
  /* A phone outline: rounded body with a short speaker line. */
  const rctf body = {x0, x0 + glyph_w, cy - 8.0f * u, cy + 8.0f * u};
  cinema_outline(body, 3.0f * u, text, std::max(1.0f, 1.2f * u));
  const rctf speaker = {x0 + glyph_w * 0.3f, x0 + glyph_w * 0.7f, cy + 4.5f * u, cy + 5.5f * u};
  cinema_fill(speaker, 0.5f * u, text);
  if (!compact) {
    cinema_text_left(label, x0 + glyph_w + glyph_gap, cy, CINEMA_FONT_VALUE * u, text);
  }

  cinema_op_button(block, "MIXAR_OT_virtual_camera_toggle", rect, tooltip);
  cinema_qa_record(region,
                   rect,
                   "director_phone",
                   status.connected ? "connected" : status.running ? "pairing" : "off",
                   -1);
}

void cinema_draw_phone_card(ui::Block *block, const bContext *C, const ARegion *region)
{
  PointerRNA wm_ptr = {};
  if (!wm_pointer(C, &wm_ptr)) {
    return;
  }
  PhoneState state;
  state.running = mirror_bool(&wm_ptr, "mixar_virtual_camera_running");
  state.connected = mirror_bool(&wm_ptr, "mixar_virtual_camera_connected");
  /* The card is the WAITING state: a paired phone wants the stage clear, and
   * a stopped server has nothing to scan. */
  if (!state.running || state.connected) {
    return;
  }
  state.tls = mirror_bool(&wm_ptr, "mixar_virtual_camera_tls");
  state.qr_side = std::min(mirror_int(&wm_ptr, "mixar_virtual_camera_qr_size"),
                           PHONE_QR_MAX_SIDE);
  mirror_string(&wm_ptr, "mixar_virtual_camera_url", state.url, sizeof(state.url));
  mirror_string(&wm_ptr, "mixar_virtual_camera_notice", state.notice, sizeof(state.notice));
  mirror_string(&wm_ptr, "mixar_virtual_camera_qr", state.qr, sizeof(state.qr));

  const float u = cinema_unit();
  const bool has_qr = state.qr_side > 0 && state.qr[0] != '\0';
  const bool warn_tls = !state.tls;
  const bool has_notice = state.notice[0] != '\0';

  float height = PHONE_CARD_PAD * 2.0f + PHONE_TITLE_H + PHONE_GAP + PHONE_LINE_H + PHONE_GAP +
                 PHONE_ROW_H;
  if (has_qr) {
    height += PHONE_QR_EDGE + PHONE_GAP;
  }
  if (warn_tls) {
    height += PHONE_LINE_H;
  }
  if (has_notice) {
    height += PHONE_LINE_H;
  }

  /* Centred on the stage (the space between the two columns), so the card
   * never covers a column the director is reading. */
  rctf stage;
  if (!cinema_stage_rect(C, region, &stage)) {
    stage = {0.0f, float(region->winx), 0.0f, float(region->winy)};
  }
  const float card_w = PHONE_CARD_W * u;
  const float card_h = height * u;
  const float cx = BLI_rctf_cent_x(&stage);
  const float cy = BLI_rctf_cent_y(&stage);
  const rctf card = {
      cx - card_w * 0.5f, cx + card_w * 0.5f, cy - card_h * 0.5f, cy + card_h * 0.5f};
  cinema_glass_panel(card, PHONE_CARD_RADIUS * u);
  /* The card is OPAQUE to clicks. Created before everything it holds, so the
   * chips and the QR still win their own pixels (`ui_but_find_mouse_over_ex`
   * walks a block backwards), but a click on the card's background stops
   * here: in Aerial mode it used to fall through to
   * `MIXAR_OT_director_place_camera`, whose poll is the stage, and move the
   * shot camera to a point hidden behind the card. */
  cinema_blocker(block, card, "Pair a phone, or Cancel to close this");

  MIXAR_THEME_LOAD(value_col, CinemaRowTextOn);
  MIXAR_THEME_LOAD(label_col, CinemaLabel);
  MIXAR_THEME_LOAD(caption_col, CinemaRowCaption);

  float y = card.ymax - PHONE_CARD_PAD * u;
  y -= PHONE_TITLE_H * u;
  cinema_text_center(has_qr ? "Scan with your phone camera" : "Open this link on your phone",
                     cx,
                     y + PHONE_TITLE_H * u * 0.5f,
                     CINEMA_FONT_TITLE * u,
                     value_col);

  if (has_qr) {
    y -= PHONE_GAP * u + PHONE_QR_EDGE * u;
    const rctf qr_area = {cx - PHONE_QR_EDGE * u * 0.5f,
                          cx + PHONE_QR_EDGE * u * 0.5f,
                          y,
                          y + PHONE_QR_EDGE * u};
    paint_qr(state, qr_area);
    /* The code itself is the pairing target: the QA harness drives it by
     * rect, and a tap on it copies the link for a phone that cannot scan. */
    cinema_op_button(block,
                     "MIXAR_OT_virtual_camera_copy_url",
                     qr_area,
                     "Copy the pairing link (open it in the phone's browser instead)");
    cinema_qa_record(region, qr_area, "director_phone_card", "qr", -1);
  }

  y -= PHONE_GAP * u + PHONE_LINE_H * u;
  text_center_fitted(state.url[0] != '\0' ? state.url : "Finding this computer on the network…",
                     cx,
                     y + PHONE_LINE_H * u * 0.5f,
                     CINEMA_FONT_LABEL * u,
                     card_w - PHONE_CARD_PAD * u * 2.0f,
                     label_col);

  if (warn_tls) {
    y -= PHONE_LINE_H * u;
    cinema_text_center("No secure link: joysticks only, no phone motion",
                       cx,
                       y + PHONE_LINE_H * u * 0.5f,
                       CINEMA_FONT_LABEL * u,
                       caption_col);
  }
  if (has_notice) {
    y -= PHONE_LINE_H * u;
    text_center_fitted(state.notice,
                       cx,
                       y + PHONE_LINE_H * u * 0.5f,
                       CINEMA_FONT_LABEL * u,
                       card_w - PHONE_CARD_PAD * u * 2.0f,
                       caption_col);
  }

  /* Actions, on their own band so nothing overlaps the link catcher above. */
  const float row_y = card.ymin + PHONE_CARD_PAD * u;
  const float gap = PHONE_GAP * u;
  const float chip_w = (card_w - PHONE_CARD_PAD * u * 2.0f - gap * 2.0f) / 3.0f;
  float chip_x = card.xmin + PHONE_CARD_PAD * u;
  const rctf copy_chip = {chip_x, chip_x + chip_w, row_y, row_y + PHONE_ROW_H * u};
  chip_x += chip_w + gap;
  const rctf repair_chip = {chip_x, chip_x + chip_w, row_y, row_y + PHONE_ROW_H * u};
  chip_x += chip_w + gap;
  const rctf stop_chip = {chip_x, chip_x + chip_w, row_y, row_y + PHONE_ROW_H * u};

  action_chip(block,
              region,
              copy_chip,
              "MIXAR_OT_virtual_camera_copy_url",
              "Copy Link",
              "Copy the pairing link to the clipboard",
              "copy");
  action_chip(block,
              region,
              repair_chip,
              "MIXAR_OT_virtual_camera_new_pairing",
              "New Code",
              "Issue a fresh pairing code and invalidate this one",
              "repair");
  action_chip(block,
              region,
              stop_chip,
              "MIXAR_OT_virtual_camera_stop",
              "Cancel",
              "Stop waiting and close the pairing server",
              "stop");
}

/** \} */

}  // namespace blender
