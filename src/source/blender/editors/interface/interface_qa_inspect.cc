/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Mixar QA harness: JSON dump of the live widget tree. See the header for
 * intent. Rects are converted to WINDOW pixel coordinates (origin bottom-left)
 * so they can be fed straight into ``Window.event_simulate``.
 */

#include <cstdint>
#include <memory>
#include <string>

#include "BLI_listbase.h"
#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "DNA_screen_types.h"
#include "DNA_windowmanager_types.h"

#include "BKE_screen.hh"

#include "RNA_access.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "interface_intern.hh"
#include "interface_qa_inspect.hh"

namespace {

void json_escape_append(std::string &out, const char *str, const size_t len)
{
  for (size_t i = 0; i < len; i++) {
    const unsigned char c = (unsigned char)str[i];
    switch (c) {
      case '"':
        out += "\\\"";
        break;
      case '\\':
        out += "\\\\";
        break;
      case '\n':
        out += "\\n";
        break;
      case '\r':
        out += "\\r";
        break;
      case '\t':
        out += "\\t";
        break;
      default:
        if (c < 0x20) {
          char buf[8];
          SNPRINTF(buf, "\\u%04x", int(c));
          out += buf;
        }
        else {
          out += char(c);
        }
        break;
    }
  }
}

void json_str(std::string &out, const char *key, const std::string &value)
{
  out += '"';
  out += key;
  out += "\":\"";
  json_escape_append(out, value.data(), value.size());
  out += '"';
}

const char *but_type_name(const ButType type)
{
  switch (type) {
    case ButType::But:
      return "But";
    case ButType::Row:
      return "Row";
    case ButType::Text:
      return "Text";
    case ButType::Menu:
      return "Menu";
    case ButType::ButMenu:
      return "ButMenu";
    case ButType::Num:
      return "Num";
    case ButType::NumSlider:
      return "NumSlider";
    case ButType::Toggle:
      return "Toggle";
    case ButType::ToggleN:
      return "ToggleN";
    case ButType::IconToggle:
      return "IconToggle";
    case ButType::IconToggleN:
      return "IconToggleN";
    case ButType::ButToggle:
      return "ButToggle";
    case ButType::Checkbox:
      return "Checkbox";
    case ButType::CheckboxN:
      return "CheckboxN";
    case ButType::Color:
      return "Color";
    case ButType::Tab:
      return "Tab";
    case ButType::Popover:
      return "Popover";
    case ButType::Scroll:
      return "Scroll";
    case ButType::Block:
      return "Block";
    case ButType::Label:
      return "Label";
    case ButType::Pulldown:
      return "Pulldown";
    case ButType::ListBox:
      return "ListBox";
    case ButType::ListRow:
      return "ListRow";
    case ButType::SearchMenu:
      return "SearchMenu";
    case ButType::HotkeyEvent:
      return "HotkeyEvent";
    case ButType::Image:
      return "Image";
    case ButType::Progress:
      return "Progress";
    default:
      return "Other";
  }
}

void qa_dump_region(std::string &out,
                    bool &first_widget,
                    const wmWindow *win,
                    const ScrArea *area, /* may be null for screen-level popups */
                    const ARegion *region,
                    const bool is_popup)
{
  if (region->flag & RGN_FLAG_HIDDEN) {
    return;
  }
  if (BLI_rcti_size_x(&region->winrct) <= 0 || BLI_rcti_size_y(&region->winrct) <= 0) {
    return;
  }
  if (region->runtime == nullptr) {
    return;
  }

  LISTBASE_FOREACH (const uiBlock *, block, &region->runtime->uiblocks) {
    for (const std::unique_ptr<uiBut> &but_ptr : block->buttons) {
      const uiBut *but = but_ptr.get();
      if (but->flag & UI_HIDDEN) {
        continue;
      }
      if (ELEM(but->type, ButType::Sepr, ButType::SeprLine)) {
        continue;
      }

      rcti pix;
      ui_but_to_pixelrect(&pix, region, block, but);

      if (!first_widget) {
        out += ',';
      }
      first_widget = false;

      out += "\n{";
      out += "\"w\":" + std::to_string(uintptr_t(win)) + ',';
      out += "\"a\":" + std::to_string(uintptr_t(area)) + ',';
      out += "\"at\":" + std::to_string(area ? int(area->spacetype) : -1) + ',';
      out += "\"r\":" + std::to_string(uintptr_t(region)) + ',';
      out += "\"rt\":" + std::to_string(int(region->regiontype)) + ',';
      if (is_popup) {
        out += "\"popup\":true,";
      }
      if (block->panel != nullptr) {
        const Panel *panel = block->panel;
        const char *panel_id = (panel->type != nullptr) ? panel->type->idname :
                                                          panel->panelname;
        json_str(out, "panel", panel_id ? panel_id : "");
        out += ',';
      }
      if (!block->name.empty()) {
        json_str(out, "block", block->name);
        out += ',';
      }

      out += "\"type\":\"";
      out += but_type_name(but->type);
      out += "\",";

      const std::string &text = but->drawstr.empty() ? but->str : but->drawstr;
      json_str(out, "text", text);
      out += ',';
      if (!but->tip.is_empty()) {
        json_str(out, "tip", std::string(but->tip.data(), size_t(but->tip.size())));
        out += ',';
      }
      if (but->optype != nullptr) {
        json_str(out, "op", but->optype->idname);
        out += ',';
      }
      if (but->rnaprop != nullptr) {
        json_str(out, "prop", RNA_property_identifier(but->rnaprop));
        out += ',';
        const char *owner = nullptr;
        if (but->rnapoin.owner_id != nullptr) {
          owner = but->rnapoin.owner_id->name + 2;
        }
        else if (but->rnapoin.type != nullptr) {
          owner = RNA_struct_identifier(but->rnapoin.type);
        }
        if (owner != nullptr) {
          json_str(out, "prop_owner", owner);
          out += ',';
        }
      }

      /* Region-space pixels -> window pixels (origin bottom-left), the same
       * space ``Window.event_simulate`` consumes. */
      const int x0 = region->winrct.xmin + pix.xmin;
      const int y0 = region->winrct.ymin + pix.ymin;
      const int x1 = region->winrct.xmin + pix.xmax;
      const int y1 = region->winrct.ymin + pix.ymax;
      out += "\"rect\":[" + std::to_string(x0) + ',' + std::to_string(y0) + ',' +
             std::to_string(x1) + ',' + std::to_string(y1) + "],";

      out += std::string("\"enabled\":") +
             (((but->flag & UI_BUT_DISABLED) == 0) ? "true" : "false");
      if (but->flag & UI_SELECT) {
        out += ",\"sel\":true";
      }
      out += '}';
    }
  }
}

}  // namespace

std::string Mixar_ui_qa_inspect_json(const wmWindowManager *wm)
{
  std::string out;
  out.reserve(1 << 16);

  out += "{\"windows\":[";
  bool first_win = true;
  LISTBASE_FOREACH (const wmWindow *, win, &wm->windows) {
    if (!first_win) {
      out += ',';
    }
    first_win = false;
    out += "{\"ptr\":" + std::to_string(uintptr_t(win)) +
           ",\"size\":[" + std::to_string(int(win->sizex)) + ',' +
           std::to_string(int(win->sizey)) + "]}";
  }
  out += "],\n\"widgets\":[";

  bool first_widget = true;
  LISTBASE_FOREACH (const wmWindow *, win, &wm->windows) {
    const bScreen *screen = WM_window_get_active_screen(win);
    if (screen == nullptr) {
      continue;
    }
    LISTBASE_FOREACH (const ScrArea *, area, &screen->areabase) {
      LISTBASE_FOREACH (const ARegion *, region, &area->regionbase) {
        qa_dump_region(out, first_widget, win, area, region, false);
      }
    }
    /* Global areas: topbar / statusbar. */
    LISTBASE_FOREACH (const ScrArea *, area, &win->global_areas.areabase) {
      LISTBASE_FOREACH (const ARegion *, region, &area->regionbase) {
        qa_dump_region(out, first_widget, win, area, region, false);
      }
    }
    /* Screen-level temporary regions: popups, menus, dropdowns, tooltips. */
    LISTBASE_FOREACH (const ARegion *, region, &screen->regionbase) {
      qa_dump_region(out, first_widget, win, nullptr, region, true);
    }
  }
  out += "\n]}";
  return out;
}
