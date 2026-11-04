/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * The Queue tab's "Why it failed" card: shown under the rows while the
 * selected job is FAILED. It answers the three questions a failed paid
 * generation raises, in order — what happened (the one-line message), why
 * (the provider's or backend's own words, redacted by the backend), and what
 * to do next (the hint, which also says whether the credits came back). The
 * full text plus support ids is the failed row's tooltip and what "Copy
 * details" puts on the clipboard (the existing `mixie.queue_copy_error`).
 *
 * All text is resolved by the Python mirror (core/failure_info.py); this file
 * only lays it out. The card has a FIXED height (QUEUE_FAILURE_CARD_H) so the
 * row capacity — which the navigation operator recomputes without drawing —
 * never depends on how long a reason is: long text wraps, and the last line
 * that fits is elided.
 */

#include <algorithm>
#include <cstring>

#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "GPU_state.hh"

#include "RNA_access.hh"

#include "UI_interface.hh"
#include "UI_interface_c.hh"

#include "WM_types.hh"

#include "UI_mixar.hh"
#include "UI_mixar_tokens.hh"
#include "agent_ui_pane_kit.hh"
#include "agent_ui_queue_intern.hh"
#include "agent_ui_text.hh"

namespace blender::agent_queue {

Vector<std::string> wrap_text(const std::string &text,
                              const float max_width,
                              const float size,
                              const int max_lines)
{
  Vector<std::string> lines;
  if (text.empty() || max_lines <= 0 || max_width <= 0.0f) {
    return lines;
  }
  std::string line;
  size_t pos = 0;
  while (pos < text.size()) {
    /* Next word, keeping the separator on the word that follows it. */
    size_t end = text.find(' ', pos);
    if (end == std::string::npos) {
      end = text.size();
    }
    const std::string word = text.substr(pos, end - pos);
    pos = end + 1;
    if (word.empty()) {
      continue;
    }
    const std::string candidate = line.empty() ? word : line + " " + word;
    if (line.empty() || ui::mixar_text_width(candidate.c_str(), size) <= max_width) {
      line = candidate;
      continue;
    }
    if (lines.size() + 1 == max_lines) {
      /* Last line: everything left is elided onto it (fit adds the "…"). */
      std::string rest = line + " " + word;
      if (pos < text.size()) {
        rest += " " + text.substr(pos);
      }
      lines.append(ui::mixar_fit_text(rest.c_str(), max_width, size));
      return lines;
    }
    /* A single word wider than the line is elided rather than overflowing. */
    lines.append(ui::mixar_fit_text(line.c_str(), max_width, size));
    line = word;
  }
  if (!line.empty()) {
    lines.append(ui::mixar_fit_text(line.c_str(), max_width, size));
  }
  return lines;
}

void failure_card_draw(ui::Block *block,
                       const QueueFailure &failure,
                       const rctf &card,
                       const float u)
{
  const auto &palette = ui::mixar_tokens::mixar_zen();
  const ui::MixarTextStyle title_style = ui::mixar_text_style(ui::MixarTextRole::ListTitle,
                                                              agent_ui_text_unit());
  const ui::MixarTextStyle body_style = ui::mixar_text_style(ui::MixarTextRole::ListMeta,
                                                             agent_ui_text_unit());

  /* Backplate: a faint danger wash, so the card reads as "about the failed
   * row" without shouting over the list. */
  float wash[4] = {palette.danger[0], palette.danger[1], palette.danger[2], 0.10f};
  pane_fill_round(&card, 12.0f * u, wash);
  float edge[4] = {palette.danger[0], palette.danger[1], palette.danger[2], 0.85f};
  rctf bar = {card.xmin, card.xmin + 4.0f * u, card.ymin + 10.0f * u, card.ymax - 10.0f * u};
  pane_fill_round(&bar, 2.0f * u, edge);

  const float pad = 18.0f * u;
  const float left = card.xmin + pad;
  const float right = card.xmax - pad;
  const float line_h = body_style.size * 1.45f;
  float y = card.ymax - pad - title_style.size * 0.5f;

  /* Header: "Why it failed · <headline>" and Copy details on the right. */
  const char *copy_label = "Copy details";
  const float copy_w = pane_action_chip_w(copy_label, false, u);
  const float control_h = ui::mixar_tokens::control_height * u;
  ui::Button *copy = uiDefButO(block,
                               ui::ButtonType::But,
                               "mixie.queue_copy_error",
                               wm::OpCallContext::InvokeDefault,
                               copy_label,
                               int(right - copy_w),
                               int(y - control_h * 0.5f),
                               short(copy_w),
                               short(control_h),
                               "Copy the full error, the provider's reason and support ids");
  ui::mixar_style_button(
      copy, ui::MixarComponent::Action, ui::MixarVariant::Secondary, u, agent_ui_text_unit());
  if (copy) {
    PointerRNA *op_ptr = ui::button_operator_ptr_ensure(copy);
    RNA_string_set(op_ptr, "feature_key", failure.feature_key);
    RNA_string_set(op_ptr, "job_id", failure.job_id);
  }

  char heading[128];
  if (failure.headline[0] && !STREQ(failure.headline, "Failed")) {
    SNPRINTF(heading, "Why it failed \xC2\xB7 %s", failure.headline);
  }
  else {
    STRNCPY(heading, "Why it failed");
  }
  const std::string fitted_heading = ui::mixar_fit_text(
      heading, right - copy_w - 12.0f * u - left, title_style);
  ui::mixar_label_left(fitted_heading.c_str(), left, y, title_style, palette.danger);
  y -= control_h * 0.5f + line_h * 0.75f;

  /* Body lines, budgeted so the card never overflows: message first, then
   * the provider's reason, then the hint. */
  const float width = right - left;
  int budget = std::max(0, int((y - (card.ymin + pad * 0.6f)) / line_h) + 1);
  auto paint = [&](const std::string &text, const int max_lines, const float *color) {
    if (budget <= 0 || text.empty()) {
      return;
    }
    for (const std::string &line : wrap_text(text, width, body_style.size, std::min(budget, max_lines))) {
      ui::mixar_label_left(line.c_str(), left, y, body_style, color);
      y -= line_h;
      budget--;
    }
  };
  paint(failure.message, 2, palette.text);
  if (!failure.reason.empty()) {
    paint("Reason: " + failure.reason, 3, palette.secondary);
  }
  paint(failure.hint, 2, palette.focus);
}

}  // namespace blender::agent_queue
