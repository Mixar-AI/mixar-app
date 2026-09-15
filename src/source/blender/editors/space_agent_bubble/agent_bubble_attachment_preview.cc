/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** Interactive, bounded attachment previews using native popup ownership. */

#include <algorithm>
#include <string>

#include "BKE_context.hh"
#include "BKE_image.hh"
#include "DNA_screen_types.h"
#include "IMB_imbuf.hh"
#include "IMB_imbuf_types.hh"
#include "MEM_guardedalloc.h"
#include "RNA_access.hh"
#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_mixar.hh"
#include "WM_api.hh"
#include "WM_types.hh"

#include "agent_bubble_attachment_preview.hh"

namespace blender {

Image *footer_thumbnails_load_image(Main *bmain, const char *path, int source);

namespace {
struct Preview {
  std::string path;
  std::string source;
  std::string name;
  int anchor_top;
};

void preview_free(void *data)
{
  MEM_delete(static_cast<Preview *>(data));
}

void *preview_copy(const void *data)
{
  return MEM_new<Preview>(__func__, *static_cast<const Preview *>(data));
}

ui::Block *preview_create(bContext *C, ARegion *region, void *arg)
{
  const Preview &preview = *static_cast<const Preview *>(arg);
  ui::Block *block = ui::block_begin(C, region, __func__, ui::EmbossType::Emboss);
  ui::block_flag_enable(block, ui::BLOCK_LOOP | ui::BLOCK_MOVEMOUSE_QUIT);
  ui::block_theme_style_set(block, ui::BLOCK_THEME_STYLE_POPUP);
  ui::block_direction_set(block, ui::UI_DIR_UP);
  const int pad = UI_UNIT_X / 2;
  const int title_h = UI_UNIT_Y * 1.4f;
  const wmWindow *win = CTX_wm_window(C);
  const int max_w = std::max(UI_UNIT_X * 2,
                             std::min(UI_UNIT_X * 16, WM_window_native_pixel_x(win) - 4 * pad));
  /* Reserve space above the thumbnail for the title, popup padding and
   * native top margin, keeping the X visible without menu scrolling. */
  const int max_h = std::max(
      UI_UNIT_Y * 2,
      std::min(UI_UNIT_Y * 14,
               WM_window_native_pixel_y(win) - preview.anchor_top - title_h - 6 * pad));
  ImBuf *scaled = nullptr;
  if (preview.source == "FILE" || preview.source == "BLEND_DATA") {
    Image *image = footer_thumbnails_load_image(
        CTX_data_main(C), preview.path.c_str(), preview.source == "BLEND_DATA" ? 1 : 0);
    if (image) {
      void *lock = nullptr;
      ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
      if (ibuf && ibuf->x > 0 && ibuf->y > 0) {
        const float fit = std::min(float(max_w) / ibuf->x, float(max_h) / ibuf->y);
        scaled = IMB_scale_into_new(
            ibuf,
            {std::max(1, int(ibuf->x * fit)), std::max(1, int(ibuf->y * fit))},
            IMBScaleFilter::Bilinear);
      }
      BKE_image_release_ibuf(image, ibuf, lock);
    }
  }
  const int image_h = scaled ? scaled->y : UI_UNIT_Y * 3;
  const int width = std::min(max_w, std::max(UI_UNIT_X * 9, scaled ? scaled->x : 0));
  if (scaled) {
    /* The native image button owns this bounded snapshot and frees it when
     * the popup closes; no Image/attachment pointer survives mutation. */
    uiDefButImage(block, scaled, (width - scaled->x) / 2, 0, scaled->x, scaled->y, nullptr);
  }
  else {
    uiDefBut(block,
             ui::ButtonType::Label,
             "Preview unavailable",
             0,
             0,
             width,
             image_h,
             nullptr,
             0,
             0,
             std::nullopt);
  }
  uiDefBut(block,
           ui::ButtonType::Label,
           preview.name,
           0,
           image_h + pad,
           width - title_h,
           title_h,
           nullptr,
           0,
           0,
           std::nullopt);
  ui::Button *remove = uiDefIconButO(block,
                                     ui::ButtonType::But,
                                     "mixie_chat.remove_attachment",
                                     wm::OpCallContext::ExecDefault,
                                     ICON_X,
                                     width - title_h,
                                     image_h + pad,
                                     title_h,
                                     title_h,
                                     "Remove this attachment");
  PointerRNA *props = ui::button_operator_ptr_ensure(remove);
  RNA_string_set(props, "attachment_path", preview.path.c_str());
  RNA_string_set(props, "attachment_source", preview.source.c_str());
  ui::block_bounds_set_normal(block, pad);
  return block;
}
}  // namespace

void agent_bubble_attachment_preview_button(const bContext *C,
                                            ui::Block *block,
                                            PointerRNA *item,
                                            const int x,
                                            const int y,
                                            const int size)
{
  auto *preview = MEM_new<Preview>(__func__);
  preview->anchor_top = CTX_wm_region(C)->winrct.ymin + y + size;
  preview->path = RNA_string_get(item, "image_path");
  preview->name = RNA_string_get(item, "display_name");
  PropertyRNA *source = RNA_struct_find_property(item, "image_source");
  const char *identifier = nullptr;
  if (source && RNA_property_enum_identifier(const_cast<bContext *>(C),
                                             item,
                                             source,
                                             RNA_property_enum_get(item, source),
                                             &identifier))
  {
    preview->source = identifier;
  }
  ui::Button *button = uiDefBlockButN(block,
                                      preview_create,
                                      preview,
                                      "",
                                      x,
                                      y,
                                      size,
                                      size,
                                      "Preview reference",
                                      preview_free,
                                      preview_copy);
  ui::button_menu_hover_delay_set(button, 0.25f);
  ui::mixar_button_tooltip_owned(button, ("Preview reference: " + preview->name).c_str());
}
}  // namespace blender
