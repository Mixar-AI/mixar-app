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
#include <vector>

#include "BLI_listbase.h"
#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "DNA_screen_types.h"
#include "DNA_windowmanager_types.h"

#include "BKE_screen.hh"

#include "RNA_access.hh"

#include "UI_interface_c.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "interface_intern.hh"
#include "interface_qa_inspect.hh"

struct MixarQAProviderEntry {
  int spacetype;
  MixarQATargetProvider fn;
};

/* Registration happens once per spacetype during startup; reads are
 * main-thread only, so no locking is needed. */
static std::vector<MixarQAProviderEntry> &qa_providers()
{
  static std::vector<MixarQAProviderEntry> providers;
  return providers;
}

void Mixar_qa_register_target_provider(int spacetype, MixarQATargetProvider fn)
{
  qa_providers().push_back({spacetype, fn});
}

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

const char *but_type_name(const blender::ui::ButtonType type)
{
  using blender::ui::ButtonType;
  switch (type) {
    case ButtonType::But:
      return "But";
    case ButtonType::Row:
      return "Row";
    case ButtonType::Text:
      return "Text";
    case ButtonType::Menu:
      return "Menu";
    case ButtonType::ButMenu:
      return "ButMenu";
    case ButtonType::Num:
      return "Num";
    case ButtonType::NumSlider:
      return "NumSlider";
    case ButtonType::Toggle:
      return "Toggle";
    case ButtonType::ToggleN:
      return "ToggleN";
    case ButtonType::IconToggle:
      return "IconToggle";
    case ButtonType::IconToggleN:
      return "IconToggleN";
    case ButtonType::ButToggle:
      return "ButToggle";
    case ButtonType::Checkbox:
      return "Checkbox";
    case ButtonType::CheckboxN:
      return "CheckboxN";
    case ButtonType::Color:
      return "Color";
    case ButtonType::Tab:
      return "Tab";
    case ButtonType::Popover:
      return "Popover";
    case ButtonType::Scroll:
      return "Scroll";
    case ButtonType::Block:
      return "Block";
    case ButtonType::Label:
      return "Label";
    case ButtonType::Pulldown:
      return "Pulldown";
    case ButtonType::ListBox:
      return "ListBox";
    case ButtonType::ListRow:
      return "ListRow";
    case ButtonType::SearchMenu:
      return "SearchMenu";
    case ButtonType::HotkeyEvent:
      return "HotkeyEvent";
    case ButtonType::Image:
      return "Image";
    case ButtonType::Progress:
      return "Progress";
    default:
      return "Other";
  }
}

/* A widget scrolled out of its region still has valid geometry, but in window
 * space that rect lands outside the region — often on top of a different area
 * entirely. Clicking its centre would hit the wrong thing, so intersect with
 * the region and drop anything with nothing left visible. */
bool qa_clip_to_region(const ARegion *region, rcti *rect)
{
  rcti clipped;
  if (!BLI_rcti_isect(rect, &region->winrct, &clipped)) {
    return false;
  }
  if (BLI_rcti_size_x(&clipped) <= 0 || BLI_rcti_size_y(&clipped) <= 0) {
    return false;
  }
  *rect = clipped;
  return true;
}

void qa_emit_custom_targets(std::string &out,
                            bool &first_widget,
                            const wmWindow *win,
                            const ScrArea *area,
                            const ARegion *region)
{
  std::vector<MixarQATarget> targets;

  /* Sidebar category tabs (the vertical "Image Gen / Video Gen / ..." strip):
   * drawn by the panel-category system, not uiButs — export their stored
   * rects so tab switching is a semantic click. */
  if (region->runtime != nullptr &&
      !BLI_listbase_is_empty(&region->runtime->panels_category))
  {
    const char *active = blender::ui::panel_category_active_get(const_cast<ARegion *>(region),
                                                     false);
    for (const PanelCategoryDyn &pc : region->runtime->panels_category)
    {
      MixarQATarget t;
      t.surface = "panel_tab";
      t.text = pc.idname;
      t.sel = (active != nullptr && STREQ(active, pc.idname));
      t.rect_win.xmin = region->winrct.xmin + pc.rect.xmin;
      t.rect_win.xmax = region->winrct.xmin + pc.rect.xmax;
      t.rect_win.ymin = region->winrct.ymin + pc.rect.ymin;
      t.rect_win.ymax = region->winrct.ymin + pc.rect.ymax;
      targets.push_back(std::move(t));
    }
  }

  for (const MixarQAProviderEntry &entry : qa_providers()) {
    if (entry.spacetype == area->spacetype) {
      entry.fn(win, area, region, targets);
    }
  }
  for (const MixarQATarget &t : targets) {
    rcti rect = t.rect_win;
    if (!qa_clip_to_region(region, &rect)) {
      continue;
    }
    if (!first_widget) {
      out += ',';
    }
    first_widget = false;
    out += "\n{";
    out += "\"w\":" + std::to_string(uintptr_t(win)) + ',';
    out += "\"a\":" + std::to_string(uintptr_t(area)) + ',';
    out += "\"at\":" + std::to_string(int(area->spacetype)) + ',';
    out += "\"r\":" + std::to_string(uintptr_t(region)) + ',';
    out += "\"rt\":" + std::to_string(int(region->regiontype)) + ',';
    out += "\"type\":\"Custom\",";
    json_str(out, "surface", t.surface);
    out += ',';
    json_str(out, "text", t.text);
    out += ',';
    if (!t.value.empty()) {
      json_str(out, "value", t.value);
      out += ',';
    }
    if (!t.detail.empty()) {
      json_str(out, "detail", t.detail);
      out += ',';
    }
    if (t.index >= 0) {
      out += "\"index\":" + std::to_string(t.index) + ',';
    }
    out += "\"rect\":[" + std::to_string(rect.xmin) + ',' + std::to_string(rect.ymin) +
           ',' + std::to_string(rect.xmax) + ',' + std::to_string(rect.ymax) + "],";
    out += std::string("\"enabled\":") + (t.enabled ? "true" : "false");
    if (t.sel) {
      out += ",\"sel\":true";
    }
    out += '}';
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
  if (area != nullptr) {
    qa_emit_custom_targets(out, first_widget, win, area, region);
  }
  if (region->runtime == nullptr) {
    return;
  }

  for (const blender::ui::Block &block : region->runtime->uiblocks) {
    for (const std::unique_ptr<blender::ui::Button> &but_ptr : block.buttons_ptrs) {
      const blender::ui::Button *but = but_ptr.get();
      if (but->flag & blender::ui::UI_HIDDEN) {
        continue;
      }
      if (ELEM(but->type, blender::ui::ButtonType::Sepr, blender::ui::ButtonType::SeprLine)) {
        continue;
      }

      rcti pix;
      blender::ui::button_to_pixelrect(&pix, region, &block, but);

      /* Region-space pixels -> window pixels (origin bottom-left), the same
       * space ``Window.event_simulate`` consumes. Clipped to the region so a
       * scrolled-away button never reports a rect over some other area. */
      rcti rect;
      rect.xmin = region->winrct.xmin + pix.xmin;
      rect.xmax = region->winrct.xmin + pix.xmax;
      rect.ymin = region->winrct.ymin + pix.ymin;
      rect.ymax = region->winrct.ymin + pix.ymax;
      if (!qa_clip_to_region(region, &rect)) {
        continue;
      }

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
      if (block.panel != nullptr) {
        const blender::ui::Panel *panel = block.panel;
        const char *panel_id = (panel->type != nullptr) ? panel->type->idname :
                                                          panel->panelname;
        json_str(out, "panel", panel_id ? panel_id : "");
        out += ',';
      }
      if (!block.name.empty()) {
        json_str(out, "block", block.name);
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

      out += "\"rect\":[" + std::to_string(rect.xmin) + ',' + std::to_string(rect.ymin) +
             ',' + std::to_string(rect.xmax) + ',' + std::to_string(rect.ymax) + "],";

      out += std::string("\"enabled\":") +
             (((but->flag & blender::ui::BUT_DISABLED) == 0) ? "true" : "false");
      if (but->flag & blender::ui::UI_SELECT) {
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
  for (const wmWindow &win_ref : wm->windows) {
    const wmWindow *win = &win_ref;
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
  for (const wmWindow &win_ref : wm->windows) {
    const wmWindow *win = &win_ref;
    const bScreen *screen = WM_window_get_active_screen(win);
    if (screen == nullptr) {
      continue;
    }
    for (const ScrArea *area : screen->areabase) {
      for (const ARegion *region : area->regionbase) {
        qa_dump_region(out, first_widget, win, area, region, false);
      }
    }
    /* Global areas: topbar / statusbar. */
    for (const ScrArea *area : win->global_areas.areabase) {
      for (const ARegion *region : area->regionbase) {
        qa_dump_region(out, first_widget, win, area, region, false);
      }
    }
    /* Screen-level temporary regions: popups, menus, dropdowns, tooltips. */
    for (const ARegion *region : screen->regionbase) {
      qa_dump_region(out, first_widget, win, nullptr, region, true);
    }
  }
  out += "\n]}";
  return out;
}
