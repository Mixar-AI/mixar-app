/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief The controls a moodboard node draws on and around its own card.
 *
 * Split out of #mixie_draw_moodboard_node_ui.cc (500-line rule), which keeps
 * the settings panel docked beside the card. These are the two surfaces a node
 * has and they answer different questions: the panel is "how should this
 * generate", the card is "what should it generate, and go" — plus, once it
 * has generated, the action row floating just above it.
 *
 * Laid out in CANVAS units from the node's own rect, like the panel, so they
 * scale and pan with the card.
 */

#include "mixie_draw_moodboard_intern.hh"

#include "DNA_theme_types.h"   /* UI_SCALE_FAC */
#include "DNA_userdef_types.h" /* extern UserDef U (used by UI_SCALE_FAC) */

#include <optional>

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_resources.hh"

namespace blender::ed::mixie {

/* Margin the tile's own controls sit in, as a fraction of the card so it holds
 * at any card size. Canvas units. */
static int tile_margin(const rctf &node_rect)
{
  return std::max(14, int(BLI_rctf_size_x(&node_rect)) / 24);
}

void moodboard_add_node_card_actions(uiBlock *block,
                                     const rctf &node_rect,
                                     const bool edit_mode,
                                     const bool has_media_result,
                                     const char *node_id)
{
  /* Floats OUTSIDE the card, on the row just above its top edge -- the same
   * relationship the settings panel has to the card's left edge. A finished
   * card is entirely its RESULT, so nothing is laid over the image.
   *
   * Square icon buttons: the row sits in the user's way, so it stays as small
   * as a comfortable target allows. The words bought nothing a pencil and an
   * arrow do not say, and cost the width of two labels above every card.
   *
   * The row height and lift are shared with the header text painted on this
   * same line (mixie_draw_moodboard_graph_chrome.cc), so the two cannot end up
   * on different lines. They never collide: the text's right side carries the
   * live state, which only exists while generating, and these icons only exist
   * once the node has finished. */
  const int height = int(MOODBOARD_NODE_HEADER_ROW_H * UI_SCALE_FAC);
  const int width = height;
  const int gap = int(8 * UI_SCALE_FAC);
  const int row_y = int(node_rect.ymax + MOODBOARD_NODE_HEADER_LIFT * UI_SCALE_FAC);

  /* Laid out from the right edge. Export claims the corner and Edit steps left
   * of it: reading order puts "adjust" before "take it away". */
  int x = int(node_rect.xmax) - width;

  /* Only a node whose result is MEDIA can be saved from here. A 3D result is an
   * object in the scene, not a board item, so there is nothing for the
   * moodboard exporter to write and the button stays off rather than opening a
   * file dialog that can only fail. */
  if (has_media_result) {
    /* ICON_IMPORT, not ICON_EXPORT: those names are from Blender's point of
     * view (data leaving the file), but the glyph is what the user reads, and
     * the arrow pointing INTO the tray is the download sign. ICON_EXPORT's
     * outward arrow reads as upload -- the opposite of what this does.
     *
     * InvokeDefault, not ExecDefault: the exporter opens a file dialog, and
     * exec'ing straight through would write to whatever path it last held. */
    uiBut *save = uiDefIconButO(block,
                                ButType::But,
                                "MIXIE_OT_moodboard_export_images",
                                blender::wm::OpCallContext::InvokeDefault,
                                ICON_IMPORT,
                                x,
                                row_y,
                                width,
                                height,
                                nullptr);
    /* Scoped to THIS node, so the button on this card saves this card's result
     * even when several nodes are selected. */
    RNA_string_set(UI_but_operator_ptr_ensure(save), "node_id", node_id);
    moodboard_set_node_tooltip(
        save, "Export\n\nSave this node's generated result to disk.");
    x -= width + gap;

    /* Between Edit and Export, which is the order the actions are reached in:
     * adjust it, look at it, take it away. A card is a thumbnail sized for the
     * graph, so judging a result means opening it at its own size. */
    uiBut *preview = uiDefIconButO(block,
                                   ButType::But,
                                   "MIXIE_OT_moodboard_preview_media",
                                   blender::wm::OpCallContext::ExecDefault,
                                   ICON_WINDOW,
                                   x,
                                   row_y,
                                   width,
                                   height,
                                   nullptr);
    RNA_string_set(UI_but_operator_ptr_ensure(preview), "node_id", node_id);
    moodboard_set_node_tooltip(
        preview,
        "Preview\n\nOpen this result in its own window. Several previews can "
        "be open at once.");
    x -= width + gap;
  }

  /* Edit toggles the settings panel and the prompt back in and out. It replaced
   * an "Edit & Run Again" row buried in the panel -- only reachable once the
   * panel was already open, and it reset the node's state to DRAFT just to make
   * the prompt reappear.
   *
   * While editing it is CANCEL, not "Done": finishing an edit means pressing
   * Generate, which the open tile already offers. The only thing this button
   * can mean there is backing out and keeping the existing result -- hence the
   * cross rather than a checkmark, which would read as a second, competing
   * confirm beside Generate. */
  uiBut *toggle = uiDefIconButO(block,
                                ButType::But,
                                "MIXIE_OT_moodboard_toggle_node_edit",
                                blender::wm::OpCallContext::ExecDefault,
                                edit_mode ? ICON_X : ICON_GREASEPENCIL,
                                x,
                                row_y,
                                width,
                                height,
                                nullptr);
  RNA_string_set(UI_but_operator_ptr_ensure(toggle), "node_id", node_id);
  moodboard_set_node_tooltip(
      toggle,
      edit_mode ?
          "Cancel edit\n\nStop editing without generating, and show this "
          "node's result again. Any settings changed stay on the node." :
          "Edit\n\nShow this node's settings and prompt so it can be "
          "adjusted and run again.");
}

void moodboard_add_node_tile_controls(uiBlock *block,
                                      PointerRNA *node,
                                      const rctf &node_rect,
                                      const bool generation_running,
                                      const bool has_result,
                                      const int state,
                                      const bool edit_mode,
                                      const char *node_id)
{
  if (generation_running) {
    /* The tile already carries the Queued/Generating hint and the glow; the
     * prompt and Generate would draw disabled straight over that text. The
     * one action that makes sense mid-flight is stopping it. Canvas units,
     * like the panel: these controls belong to the tile and scale with it. */
    const int prompt_margin = tile_margin(node_rect);
    const int cancel_h = int(36 * UI_SCALE_FAC);
    const int cancel_w = int(118 * UI_SCALE_FAC);
    uiBut *cancel = uiDefButO(block,
                              ButType::But,
                              "MIXIE_OT_moodboard_cancel_action_node",
                              blender::wm::OpCallContext::ExecDefault,
                              "Cancel",
                              int(node_rect.xmax) - prompt_margin - cancel_w,
                              int(node_rect.ymin) + prompt_margin,
                              cancel_w,
                              cancel_h,
                              nullptr);
    RNA_string_set(UI_but_operator_ptr_ensure(cancel), "node_id", node_id);
  }
  else if (!has_result || state == 0 || edit_mode) {
    /* Either the node has nothing to show yet, or the user turned Edit on over
     * a finished result -- the prompt and Generate draw over the tile so it can
     * be adjusted and re-run in place. */
    const int prompt_margin = tile_margin(node_rect);
    /* UI-factor sized like the left panel: the label renders at UI_SCALE_FAC,
     * so a fixed 118px clipped "Generate" to "Gener..." at high UI scale. */
    const int generate_h = int(36 * UI_SCALE_FAC);
    const int generate_w = int(118 * UI_SCALE_FAC);
    /* Make the prompt a tall multi-line text area: it spans from the top margin
     * down to just above the Generate button. Height comfortably exceeds
     * UI_UNIT_Y * 1.5 at any UI scale, which is what flips the native text
     * button into the word-wrapping, scrollable multi-line renderer
     * (ui_but_is_multiline_text). A fixed short band stayed single-line on
     * high-DPI displays where UI_UNIT_Y is large. */
    /* Mesh-only nodes (Retopology / Mesh Segmentation / Auto Rig) take no text
     * guidance, so they hide the prompt field entirely; the Generate button
     * below is still drawn. */
    if (RNA_boolean_get(node, "show_prompt")) {
      const int prompt_top = int(node_rect.ymax) - prompt_margin;
      const int prompt_bottom = int(node_rect.ymin) + prompt_margin + generate_h + 12;
      const int prompt_height = std::max(46, prompt_top - prompt_bottom);
      const int prompt_y = prompt_top - prompt_height;
      /* Bound straight to the node's own `prompt` property. The settings
       * panel's shared helper is file-static over in node_ui.cc and sharing it
       * would mean dragging the UI headers that define ButType into a draw
       * header many translation units include; this is the only prop-bound
       * field the tile has. */
      uiBut *prompt = RNA_struct_find_property(node, "prompt") ?
                          uiDefButR(block,
                                    ButType::Text,
                                    0,
                                    "",
                                    int(node_rect.xmin) + prompt_margin,
                                    prompt_y,
                                    short(int(BLI_rctf_size_x(&node_rect)) -
                                          prompt_margin * 2),
                                    short(prompt_height),
                                    node,
                                    "prompt",
                                    -1,
                                    0.0f,
                                    0.0f,
                                    std::nullopt) :
                          nullptr;
      if (prompt) {
        UI_but_placeholder_set(prompt, "Describe what you want to create...");
        UI_but_flag_enable(prompt, UI_BUT_TEXTEDIT_UPDATE);
        moodboard_set_node_tooltip(
            prompt,
            "Prompt\n\nDescribe what to generate. Press Enter to submit "
            "this node.");
      }
    }

    uiBut *generate = uiDefButO(block,
                                ButType::But,
                                "MIXIE_OT_moodboard_run_action_node",
                                blender::wm::OpCallContext::ExecDefault,
                                "Generate",
                                int(node_rect.xmax) - prompt_margin - generate_w,
                                int(node_rect.ymin) + prompt_margin,
                                generate_w,
                                generate_h,
                                nullptr);
    RNA_string_set(UI_but_operator_ptr_ensure(generate), "node_id", node_id);
  }
}

}  // namespace blender::ed::mixie
