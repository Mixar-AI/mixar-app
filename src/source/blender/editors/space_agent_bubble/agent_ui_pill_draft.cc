/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** Live draft preview in the minimized sketch pill. Drawing and QA share bounds. */
#include <string>

#include "BLI_listbase.h"
#include "BLI_rect.h"
#include "BLI_utildefines.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "../interface/interface_qa_inspect.hh"
#include "agent_ui_draw_primitives.hh"
#include "agent_ui_pill_draft.hh"
#include "agent_ui_theme.hh"

namespace blender {
namespace {
rcti preview_rect;
std::string preview_text;
std::string preview_draft;
bool preview_valid = false;

void draft_targets(const wmWindow *, const ScrArea *area, const ARegion *region,
                   std::vector<MixarQATarget> &targets)
{
  if (!preview_valid || !area || !region || area->spacetype != SPACE_AGENT_BUBBLE ||
      region->regiontype != RGN_TYPE_HEADER)
  {
    return;
  }
  for (const ARegion &other : area->regionbase) {
    if (ELEM(other.regiontype, RGN_TYPE_WINDOW, RGN_TYPE_TOOLS)) {
      return;
    }
  }
  MixarQATarget target;
  target.surface = "pill_draft_preview";
  target.text = preview_text;
  target.value = preview_draft;
  target.rect_win = preview_rect;
  BLI_rcti_translate(&target.rect_win, region->winrct.xmin, region->winrct.ymin);
  targets.push_back(std::move(target));
}
}  // namespace

void agent_ui_draw_pill_draft(const char *draft, const float left, const float right,
                              const float height, const float font_size, const char *voice_status)
{
  preview_draft = draft;
  std::string text = preview_draft.empty() ? "Type instructions..." : preview_draft;
  for (char &c : text) {
    if (c == '\n' || c == '\r' || c == '\t') {
      c = ' ';
    }
  }
  const float width = right - left;
  size_t offset = 0;
  preview_text = text;
  // Keep the newest typed characters visible; never split a UTF-8 codepoint.
  while (text_width(preview_text.c_str(), font_size) > width && offset < text.size()) {
    do {
      offset++;
    } while (offset < text.size() && (text[offset] & 0xc0) == 0x80);
    preview_text = "..." + text.substr(offset);
  }
  const float title_color[4] = AGENT_COL_TEXT_DIM;
  const float text_color[4] = AGENT_COL_TEXT;
  const std::string title = voice_status[0] ? std::string(voice_status) + " · Enter to send" :
                                             "Sketch · Enter to send";
  label_left(title.c_str(), left, height * 0.72f, font_size * 0.75f, title_color);
  label_left(preview_text.c_str(), left, height * 0.32f, font_size, text_color);
  BLI_rcti_init(&preview_rect, int(left), int(right), int(height * 0.08f), int(height * 0.94f));
  preview_valid = true;
}

void agent_ui_pill_draft_clear()
{
  preview_valid = false;
}

void agent_ui_pill_draft_qa_register()
{
  Mixar_qa_register_target_provider(SPACE_AGENT_BUBBLE, draft_targets);
}
}  // namespace blender
