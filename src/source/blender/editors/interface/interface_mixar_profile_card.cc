/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Mixar account card — layout construction.
 *
 * Builds the profile dropdown's contents through the ordinary #Layout
 * API and tags each item with #UI_BUT2_MIXAR_CARD so widget dispatch
 * routes it to the card's own drawing (see
 * `interface_mixar_profile_card_draw.cc`).
 *
 * Everything the card shows is read from RNA that Python owns; nothing
 * is cached here, so a stale card is impossible and there is no second
 * source of truth for account state.
 */

#include <algorithm>
#include <cstdio>
#include <cstring>

#include "MEM_guardedalloc.h"

#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "BLT_translation.hh"

#include "DNA_scene_types.h"
#include "DNA_userdef_types.h"
#include "DNA_windowmanager_types.h"

#include "BKE_context.hh"

#include "RNA_access.hh"

#include "WM_api.hh"

#include "UI_interface_c.hh"
#include "UI_interface_layout.hh"
#include "UI_resources.hh"

#include "interface_intern.hh"
#include "interface_mixar_card_icons.hh"
#include "interface_mixar_card_paint.hh"
#include "interface_mixar_profile_card.hh"
#include "interface_mixar_section.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui {

namespace {

/* Documentation/support destinations — same URLs the previous menu used. */
constexpr const char *MIXAR_URL_DOCS = "https://www.mixar.app/docs";
constexpr const char *MIXAR_URL_BUG = "https://www.mixar.app/bug-report";

/* Dashboard handoff target for the top-up CTA; must match
 * `modules/common/usage/constants.py:HANDOFF_TARGET_*`. */
constexpr const char *MIXAR_TARGET_BUY_CREDITS = "buy-credits";
constexpr const char *MIXAR_TARGET_PRICING = "pricing";

/* Whether the card prints the raw credit figures ("4,300 of 5,000 left")
 * beside the CTA. Off for now — the percentage carries the meaning and
 * the pair reads as noise next to it, particularly where a carried-over
 * balance exceeds the cycle allocation.
 *
 * A flag rather than a deletion: the formatting, the thousands separator
 * and the balance-above-allocation branch are all still correct and
 * worth keeping intact for whenever the line comes back. The stale
 * notice shares this slot and is NOT gated by it. */
constexpr bool CARD_SHOW_CREDIT_FIGURES = false;

/* Element heights, in UI units, applied with `scale_y_set()`.
 *
 * **Not** `ui_units_y_set()**: that forces the enclosing *layout item's*
 * height, while `ui_item_size()` still reports each button's own rect —
 * created one unit tall and never told about its parent. The row grows,
 * the button does not, and the extra height becomes dead space. Only
 * `ui_item_scale()`, which `scale_y` drives, multiplies a child button's
 * height.
 *
 * That distinction is what the card's proportions rest on: #MX_R_MD is a
 * fixed 8px radius, so on a stock 20px button it lands at 0.4 of the
 * height (and the roundbox clamp takes it to h/2), which draws every
 * action as a lozenge. At #ROW_ACTION the same radius is roughly a
 * quarter of the height and reads as the intended rounded rect. */
constexpr float ROW_HEADING = 1.6f;
constexpr float ROW_USAGE_BAR = 1.5f;
constexpr float ROW_CTA = 1.7f;
constexpr float ROW_ACTION = 1.9f;
constexpr float ROW_LOGOUT = 1.7f;
constexpr float ROW_DIVIDER = 0.6f;

/* -------------------------------------------------------------------- */
/* Measuring                                                             */

/**
 * Width in UI units that \a text needs when the card paints it itself.
 *
 * The card suppresses the stock text pass and draws with its own font
 * scale and padding, but the *layout* still sizes each button from the
 * default widget font — so anything the painter spends beyond that
 * estimate comes off the end of the string. #fontstyle_draw clips to
 * the rect through #BLF_clipping with no ellipsis, so the overflow is
 * silent: "Logout" simply renders as "Log".
 *
 * Measuring here closes that gap at the only point that knows both
 * numbers, and does it in whatever language the UI is running in.
 *
 * \param chrome_px: Everything the painter draws besides the glyphs —
 * padding, icon slot and gap.
 */
float card_units_for_text(const char *text,
                          const float scale,
                          const int weight,
                          const float chrome_px)
{
  if (text == nullptr || text[0] == '\0') {
    return chrome_px / float(UI_UNIT_X);
  }
  const uiFontStyle fs = mixar_card_font(scale, weight);
  const float width = float(fontstyle_string_width(&fs, text));
  return (width + chrome_px) / float(UI_UNIT_X);
}

/* -------------------------------------------------------------------- */
/* Tagging                                                               */

/** Tag the most recently created button as a card element. */
void mark_last(Layout *layout, const MixarCardElement element, const float payload = 0.0f)
{
  Block *block = layout->block();
  if (block->buttons_ptrs.is_empty()) {
    return;
  }
  Button *but = block->buttons_ptrs.last().get();
  UI_BUT2_MIXAR_CARD_SET(but);
  /* `hardmin`/`hardmax` are inert on the label and operator buttons used
   * here — neither carries a data pointer or RNA property, so
   * `ui_but_value_get()` returns before reading them, and the
   * `hardmin <= hardmax` assertion in `ui_but_update_ex()` is scoped to
   * Num/Scroll/NumSlider. */
  but->hardmin = float(int(element));
  /* For buttons the payload is the #MixarCardIcon; for the quota bar it
   * is the fill fraction. */
  but->hardmax = payload;
}

/* -------------------------------------------------------------------- */
/* RNA reads                                                             */

struct AccountInfo {
  char name[128] = {0};
  char email[256] = {0};
  char plan_name[64] = {0};
  bool logged_in = false;
  bool usage_ready = false;
  bool has_subscription = false;
  bool can_top_up = false;
  bool stale = false;
  float remaining_pct = 0.0f;
  int credits_remaining = 0;
  int credits_total = 0;
};

/** Read a string property, leaving \a dst empty when it is absent. */
void read_string(PointerRNA *ptr, const char *name, char *dst, const int dst_maxncpy)
{
  dst[0] = '\0';
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  if (prop == nullptr) {
    return;
  }
  int len = 0;
  char *value = RNA_property_string_get_alloc(ptr, prop, dst, dst_maxncpy, &len);
  if (value != nullptr && value != dst) {
    BLI_strncpy(dst, value, dst_maxncpy);
    MEM_delete_void(static_cast<void *>(value));
  }
}

bool read_bool(PointerRNA *ptr, const char *name)
{
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  return prop != nullptr && RNA_property_boolean_get(ptr, prop);
}

float read_float(PointerRNA *ptr, const char *name)
{
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  return prop != nullptr ? RNA_property_float_get(ptr, prop) : 0.0f;
}

int read_int(PointerRNA *ptr, const char *name)
{
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  return prop != nullptr ? RNA_property_int_get(ptr, prop) : 0;
}

/**
 * Collect what the card draws.
 *
 * Every property is looked up defensively: UI auto-discovery registers
 * them in time-budgeted batches, so the card can be opened in the window
 * between the popover existing and the usage properties landing.
 */
AccountInfo read_account(bContext *C)
{
  AccountInfo info;

  if (wmWindowManager *wm = CTX_wm_manager(C)) {
    PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
    info.logged_in = read_bool(&wm_ptr, "mixie_chat_is_logged_in");
    info.usage_ready = read_bool(&wm_ptr, "mixar_usage_ready");
    info.has_subscription = read_bool(&wm_ptr, "mixar_usage_has_subscription");
    info.can_top_up = read_bool(&wm_ptr, "mixar_usage_can_top_up");
    info.stale = read_bool(&wm_ptr, "mixar_usage_stale");
    info.remaining_pct = read_float(&wm_ptr, "mixar_usage_remaining_pct");
    info.credits_remaining = read_int(&wm_ptr, "mixar_usage_credits_remaining");
    info.credits_total = read_int(&wm_ptr, "mixar_usage_credits_total");
    read_string(&wm_ptr, "mixar_account_name", info.name, sizeof(info.name));
    read_string(&wm_ptr, "mixar_usage_plan_name", info.plan_name, sizeof(info.plan_name));
  }

  if (Scene *scene = CTX_data_scene(C)) {
    PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
    read_string(&scene_ptr, "mixie_chat_user_id", info.email, sizeof(info.email));
  }

  return info;
}

/* -------------------------------------------------------------------- */
/* Sections                                                              */

/** Thousands-separated credit count, e.g. 4300 -> "4,300". */
void format_credits(const int value, char *dst, const int dst_maxncpy)
{
  char digits[32];
  SNPRINTF(digits, "%d", std::max(0, value));

  const int len = int(strlen(digits));
  int out = 0;
  for (int i = 0; i < len && out < dst_maxncpy - 1; i++) {
    if (i > 0 && ((len - i) % 3) == 0) {
      dst[out++] = ',';
    }
    if (out < dst_maxncpy - 1) {
      dst[out++] = digits[i];
    }
  }
  dst[out] = '\0';
}

void add_divider(Layout *layout)
{
  Layout &row = layout->row(false);
  row.scale_y_set(ROW_DIVIDER);
  row.label("", ICON_NONE);
  mark_last(&row, MixarCardElement::Divider);
}

void add_header(Layout *layout, const AccountInfo &info)
{
  Layout &row = layout->row(false);

  Layout &names = row.column(true);
  names.alignment_set(blender::ui::LayoutAlign::Left);

  char greeting[192];
  if (info.name[0]) {
    SNPRINTF(greeting, IFACE_("Welcome, %s !"), info.name);
  }
  else {
    /* No name and no email yet — greet without a dangling comma. */
    BLI_strncpy(greeting, IFACE_("Welcome !"), sizeof(greeting));
  }
  Layout &heading_row = names.row(false);
  /* Just enough headroom for the oversized glyphs; taller than this and
   * the vertical centring opens a dead gap above the email line. */
  heading_row.scale_y_set(ROW_HEADING);
  heading_row.label(greeting, ICON_NONE);
  mark_last(&heading_row, MixarCardElement::Heading);

  if (info.email[0]) {
    char email_line[288];
    SNPRINTF(email_line, "(%s)", info.email);
    names.label(email_line, ICON_NONE);
    mark_last(&names, MixarCardElement::Muted);
  }

  /* Plan chip, right-aligned against the greeting. The backend stores
   * the bare tier ("Pro"), which reads as a stray word on its own. */
  if (info.plan_name[0]) {
    char chip_text[80];
    if (BLI_strcasestr(info.plan_name, "plan") != nullptr) {
      BLI_strncpy(chip_text, info.plan_name, sizeof(chip_text));
    }
    else {
      SNPRINTF(chip_text, IFACE_("%s Plan"), info.plan_name);
    }
    Layout &chip = row.row(false);
    chip.alignment_set(blender::ui::LayoutAlign::Right);
    /* Pin the chip to what it actually paints, so the greeting beside it
     * gets every remaining pixel instead of an even split. */
    chip.ui_units_x_set(card_units_for_text(
        chip_text, MIXAR_CARD_PILL_SCALE, 0, MIXAR_CARD_PILL_PAD * 2.0f * UI_SCALE_FAC));
    chip.label(chip_text, ICON_NONE);
    mark_last(&chip, MixarCardElement::Pill);
  }
}

void add_usage(Layout *layout, const AccountInfo &info)
{
  if (!info.usage_ready) {
    /* Nothing fetched yet — say so instead of drawing an empty bar that
     * reads as "no credits". */
    layout->label(IFACE_("Checking usage…"), ICON_NONE);
    mark_last(layout, MixarCardElement::Muted);
    return;
  }

  layout->label(IFACE_("Your Usage"), ICON_NONE);
  mark_last(layout, MixarCardElement::SectionLabel);

  if (info.has_subscription) {
    const float factor = std::clamp(info.remaining_pct / 100.0f, 0.0f, 1.0f);

    char pct[16];
    /* Floor, so a nearly-exhausted cycle never rounds up into a
     * reassuring number. Mirrors `state.format_remaining_label`. */
    SNPRINTF(pct, "%d%%", int(info.remaining_pct));

    Layout &bar_row = layout->row(false);
    bar_row.scale_y_set(ROW_USAGE_BAR);
    bar_row.label(pct, ICON_NONE);
    mark_last(&bar_row, MixarCardElement::UsageBar, factor);
  }

  Layout &foot = layout->row(false);

  Layout &cta = foot.row(false);
  cta.alignment_set(blender::ui::LayoutAlign::Left);
  /* Scaled, not unit-sized: only `scale_y` reaches the button itself, and
   * the CTA at stock height is the flattest lozenge on the card. */
  cta.scale_y_set(ROW_CTA);

  /* A left-aligned row collapses to its estimated width, which is
   * measured from the default font and knows nothing about the accent
   * button's padding — so the CTA has to declare what it needs or lose
   * its last letters ("See Plans" -> "See Plan"). */
  const char *cta_label = info.can_top_up ? IFACE_("Buy Credits") : IFACE_("See Plans");
  cta.ui_units_x_set(card_units_for_text(cta_label, 1.0f, 0, mixar_card_button_chrome(false)));

  if (info.can_top_up) {
    PointerRNA props = cta.op("MIXAR_OT_open_billing", cta_label, ICON_NONE);
    RNA_string_set(&props, "target", MIXAR_TARGET_BUY_CREDITS);
  }
  else {
    /* Trial, cancelling and free accounts cannot top up — the server
     * refuses it, so offer plans rather than a button that would fail. */
    PointerRNA props = cta.op("MIXAR_OT_open_billing", cta_label, ICON_NONE);
    RNA_string_set(&props, "target", MIXAR_TARGET_PRICING);
  }
  mark_last(&cta, MixarCardElement::AccentButton);

  /* The stale notice still has to reach the user — it is the card's only
   * signal that the figures above it are old — so only the credit
   * figures are suppressed, and the row is skipped entirely when that
   * leaves nothing to say. */
  const bool show_credits = CARD_SHOW_CREDIT_FIGURES;
  if (!info.stale && !show_credits) {
    return;
  }

  Layout &meta = foot.row(false);
  meta.alignment_set(blender::ui::LayoutAlign::Right);

  char meta_text[96];
  if (info.stale) {
    BLI_strncpy(meta_text, IFACE_("couldn't refresh"), sizeof(meta_text));
  }
  else if (info.has_subscription && info.credits_total > 0) {
    /* The balance can exceed the cycle allocation — topped-up credits and
     * shared team pools both carry over. Both figures are shown as-is and
     * the meter reads 100%: the backend clamps `usage_pct` to 0 in that
     * case, which is the correct reading (nothing of the allowance is
     * spent), so the bar must be full rather than over-full. */
    char left[32], total[32];
    format_credits(info.credits_remaining, left, sizeof(left));
    format_credits(info.credits_total, total, sizeof(total));
    SNPRINTF(meta_text, IFACE_("%s of %s left"), left, total);
  }
  else if (info.credits_remaining > 0) {
    char left[32];
    format_credits(info.credits_remaining, left, sizeof(left));
    SNPRINTF(meta_text, IFACE_("%s credits"), left);
  }
  else {
    BLI_strncpy(meta_text, IFACE_("no credits"), sizeof(meta_text));
  }
  meta.label(meta_text, ICON_NONE);
  mark_last(&meta, MixarCardElement::MetaRight);
}

/**
 * One action button, or nothing when its operator is absent.
 *
 * `ICON_NONE` throughout: the card draws its own glyphs
 * (#UI_mixar_card_icon_draw), because the stock set is weighted for
 * toolbars and out-shouts the labels at card scale.
 */
void add_action(Layout *layout,
                const char *op_idname,
                const char *label,
                const MixarCardIcon icon,
                const MixarCardElement element)
{
  if (WM_operatortype_find(op_idname, true) == nullptr) {
    return;
  }
  layout->op(op_idname, IFACE_(label), ICON_NONE);
  mark_last(layout, element, float(int(icon)));
}

void add_actions(Layout *layout)
{
  Layout &grid = layout->column(false);

  Layout &top = grid.row(true);
  top.scale_y_set(ROW_ACTION);
  add_action(&top, "MIXIE_CHAT_OT_open_dashboard", "Dashboard", MixarCardIcon::Grid,
             MixarCardElement::CardButton);
  add_action(&top, "MIXAR_BYOK_OT_open_dialog", "AI Provider Settings", MixarCardIcon::Sliders,
             MixarCardElement::CardButton);

  Layout &bottom = grid.row(true);
  bottom.scale_y_set(ROW_ACTION);

  if (WM_operatortype_find("WM_OT_url_open", true) != nullptr) {
    PointerRNA docs = bottom.op("WM_OT_url_open", IFACE_("Docs"), ICON_NONE);
    RNA_string_set(&docs, "url", MIXAR_URL_DOCS);
    mark_last(&bottom, MixarCardElement::CardButton, float(int(MixarCardIcon::Document)));

    PointerRNA bug = bottom.op("WM_OT_url_open", IFACE_("Report a Bug"), ICON_NONE);
    RNA_string_set(&bug, "url", MIXAR_URL_BUG);
    mark_last(&bottom, MixarCardElement::DangerButton, float(int(MixarCardIcon::Alert)));
  }
}

void add_logout(Layout *layout)
{
  Layout &row = layout->row(false);
  row.scale_y_set(ROW_LOGOUT);
  /* Deliberately NOT centre-aligned: that collapses the row to the
   * layout's estimate of the label alone, leaving the painter's icon and
   * padding to eat the text ("Logout" -> "Log"). A full-width strip with
   * the contents centred by the painter is both the correct hit area and
   * the intended look. */
  add_action(&row, "MIXIE_CHAT_OT_logout", "Logout", MixarCardIcon::Cross,
             MixarCardElement::GhostButton);
}

}  // namespace

/* -------------------------------------------------------------------- */
/* Public API                                                            */

MixarCardElement UI_mixar_card_element_get(const Button *but)
{
  if (but == nullptr || !UI_BUT2_MIXAR_CARD_TEST(but)) {
    return MixarCardElement::None;
  }
  const int value = int(but->hardmin);
  if (value <= int(MixarCardElement::None) || value >= int(MixarCardElement::Count)) {
    return MixarCardElement::None;
  }
  return MixarCardElement(value);
}

void UI_layout_mixar_profile_card(Layout *layout, bContext *C)
{
  const AccountInfo info = read_account(C);

  Layout &card = layout->column(false);

  add_header(&card, info);
  card.separator(0.6f);
  add_usage(&card, info);

  add_divider(&card);
  add_actions(&card);
  add_divider(&card);
  add_logout(&card);
}
}  // namespace blender::ui
