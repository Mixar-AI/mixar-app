/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief The controls a moodboard node draws on and around its own card.
 *
 * Shared screen-space model/settings, prompt and action controls.
 * The Python node-settings popup owns the parameter schema renderer.
 * Both hosts use the same content bounds and native widgets.
 */

#include "mixie_draw_moodboard_intern.hh"
#include "mixie_moodboard_node_layout.hh"

#include "DNA_theme_types.h"   /* UI_SCALE_FAC */
#include "DNA_userdef_types.h" /* extern UserDef U (used by UI_SCALE_FAC) */

#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_mixar.hh"
#include "UI_resources.hh"

namespace blender::ed::mixie {

float moodboard_node_card_actions_width(const bool has_media)
{
  const float height = MOODBOARD_NODE_HEADER_ROW_H * UI_SCALE_FAC;
  const auto metrics = ui::mixar_density_metrics(ui::MixarDensity::Compact, UI_SCALE_FAC);
  return has_media ? 3.0f * height + 2.0f * metrics.gap : height;
}

void moodboard_add_node_card_actions(ui::Block *block,
                                     const rcti &card,
                                     const bool edit_mode,
                                     const bool has_media_result,
                                     const char *node_id)
{
  /* Floats OUTSIDE the card, on the row just above its top edge -- a consistent
   * header position for both canvas hosts. A finished
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
  const int gap = int(ui::mixar_density_metrics(ui::MixarDensity::Compact, UI_SCALE_FAC).gap);
  /* Like the title, actions stay attached to the card. The block clips them
   * at the canvas edge without moving them into a different row. */
  const int row_y = card.ymax + int(MOODBOARD_NODE_HEADER_LIFT * UI_SCALE_FAC);

  /* Laid out from the right edge. Export claims the corner and Edit steps left
   * of it: reading order puts "adjust" before "take it away". */
  int x = card.xmax - width;

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
    ui::Button *save = ui::uiDefIconButO(block,
                                         ui::ButtonType::But,
                                         "MIXIE_OT_moodboard_export_images",
                                         blender::wm::OpCallContext::InvokeDefault,
                                         ICON_IMPORT,
                                         x,
                                         row_y,
                                         width,
                                         height,
                                         nullptr);
    ui::mixar_style_button(
        save, ui::MixarComponent::Action, ui::MixarVariant::Secondary, UI_SCALE_FAC * 0.65f);
    /* Scoped to THIS node, so the button on this card saves this card's result
     * even when several nodes are selected. */
    RNA_string_set(ui::button_operator_ptr_ensure(save), "node_id", node_id);
    moodboard_set_node_tooltip(save, "Export\n\nSave this node's generated result to disk.");
    x -= width + gap;

    /* Between Edit and Export, which is the order the actions are reached in:
     * adjust it, look at it, take it away. A card is a thumbnail sized for the
     * graph, so judging a result means opening it at its own size. */
    ui::Button *preview = ui::uiDefIconButO(block,
                                            ui::ButtonType::But,
                                            "MIXIE_OT_moodboard_preview_media",
                                            blender::wm::OpCallContext::ExecDefault,
                                            ICON_WINDOW,
                                            x,
                                            row_y,
                                            width,
                                            height,
                                            nullptr);
    ui::mixar_style_button(
        preview, ui::MixarComponent::Action, ui::MixarVariant::Secondary, UI_SCALE_FAC * 0.65f);
    RNA_string_set(ui::button_operator_ptr_ensure(preview), "node_id", node_id);
    moodboard_set_node_tooltip(
        preview,
        "Preview\n\nOpen this result in its own window. Several previews can "
        "be open at once.");
    x -= width + gap;
  }

  /* Edit toggles the settings panel and the prompt back in and out. It is the
   * way back into a finished node: the panel's own "Edit & Run Again" is only
   * reachable once the panel is already open, and it resets the node to DRAFT.
   * This changes nothing but how the card is presented.
   *
   * While editing it is CANCEL, not "Done": finishing an edit means pressing
   * Generate, which the open tile already offers. The only thing this button
   * can mean there is backing out and keeping the existing result -- hence the
   * cross rather than a checkmark, which would read as a second, competing
   * confirm beside Generate. */
  ui::Button *toggle = ui::uiDefIconButO(block,
                                         ui::ButtonType::But,
                                         "MIXIE_OT_moodboard_toggle_node_edit",
                                         blender::wm::OpCallContext::ExecDefault,
                                         edit_mode ? ICON_X : ICON_GREASEPENCIL,
                                         x,
                                         row_y,
                                         width,
                                         height,
                                         nullptr);
  ui::mixar_style_button(
      toggle, ui::MixarComponent::Action, ui::MixarVariant::Secondary, UI_SCALE_FAC * 0.65f);
  RNA_string_set(ui::button_operator_ptr_ensure(toggle), "node_id", node_id);
  moodboard_set_node_tooltip(
      toggle,
      edit_mode ? "Cancel edit\n\nStop editing without generating, and show this "
                  "node's result again. Any settings changed stay on the node." :
                  "Edit\n\nShow this node's settings and prompt so it can be "
                  "adjusted and run again.");
}

void moodboard_add_node_tile_controls(ui::Block *block,
                                      PointerRNA *node,
                                      const rcti &tile,
                                      const bool generation_running,
                                      const bool has_result,
                                      const int state,
                                      const bool edit_mode,
                                      const char *node_id)
{
  const auto metrics = ui::mixar_density_metrics(ui::MixarDensity::Compact, UI_SCALE_FAC);
  const int margin = int(metrics.padding);
  if (generation_running) {
    /* The tile already carries the Queued/Generating hint and the glow; the
     * prompt and Generate would draw disabled straight over that text. The
     * one action that makes sense mid-flight is stopping it. */
    const int cancel_h = int(metrics.control_height);
    const int cancel_w = int(118 * UI_SCALE_FAC);
    ui::Button *cancel = ui::uiDefButO(block,
                                       ui::ButtonType::But,
                                       "MIXIE_OT_moodboard_cancel_action_node",
                                       blender::wm::OpCallContext::ExecDefault,
                                       "Cancel",
                                       tile.xmax - margin - cancel_w,
                                       tile.ymin + margin,
                                       cancel_w,
                                       cancel_h,
                                       nullptr);
    ui::mixar_style_button(
        cancel, ui::MixarComponent::Action, ui::MixarVariant::Secondary, UI_SCALE_FAC * 0.65f);
    RNA_string_set(ui::button_operator_ptr_ensure(cancel), "node_id", node_id);
  }
  /* Either the node has nothing to show yet, or the user turned Edit on over a
   * finished result -- the prompt and Generate draw over the tile so it can be
   * adjusted and re-run in place. A finished node that is NOT being edited
   * shows its result and nothing else. */
  else if (!has_result || state == 0 || edit_mode) {
    /* UI-factor sized like the left panel: the label renders at UI_SCALE_FAC,
     * so a fixed 118px clipped "Generate" to "Gener..." at high UI scale. */
    const int generate_h = int(metrics.control_height);
    const int refine_count = RNA_boolean_get(node, "show_prompt") ?
                                 (RNA_boolean_get(node, "prompt_refined") ? 2 : 1) : 0;
    /* Revert must fit without hiding the editor or changing its outer padding. */
    const int generate_w = std::min(int(118 * UI_SCALE_FAC),
                                    BLI_rcti_size_x(&tile) - 2 * margin -
                                        refine_count * (generate_h + int(metrics.gap)));
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
      const int prompt_top = tile.ymax - margin;
      const int prompt_bottom = tile.ymin + margin + generate_h + int(metrics.gap);
      const int prompt_height = prompt_top - prompt_bottom;
      const int prompt_y = prompt_top - prompt_height;
      ui::Button *prompt = moodboard_screen_prop_button(block,
                                                        node,
                                                        "prompt",
                                                        "",
                                                        ui::ButtonType::Text,
                                                        tile.xmin + margin,
                                                        prompt_y,
                                                        BLI_rcti_size_x(&tile) - margin * 2,
                                                        prompt_height);
      if (prompt) {
        ui::button_placeholder_set(prompt, "Describe your idea…");
        ui::button_flag_enable(prompt, ui::BUT_TEXTEDIT_UPDATE);
        moodboard_set_node_tooltip(
            prompt, "Prompt\n\nDescribe what to generate. Press Enter to submit this node.");
      }
    }

    /* Refine (and, once a rewrite has landed, Revert) left of Generate. The
     * prompt is the one thing on this tile the user authors by hand, so the
     * help with writing it belongs beside the field rather than in the
     * settings panel, which is folded away exactly when a draft node is
     * being written.
     *
     * Square icon buttons: the tile is small and the words would crowd
     * Generate, which must stay the obvious action.
     *
     * Laid out right to left — Generate, then Revert, then Refine — so
     * Refine keeps the same relationship to the pair whether or not Revert
     * is present, and Generate never moves. */
    if (RNA_boolean_get(node, "show_prompt")) {
      const bool refined = RNA_boolean_get(node, "prompt_refined");
      const bool refining = RNA_boolean_get(node, "prompt_refining");
      const int refine_w = generate_h;
      const int refine_gap = int(metrics.gap);
      const int refine_y = tile.ymin + margin;
      int refine_x = tile.xmax - margin - generate_w - refine_gap - refine_w;

      if (refined) {
        ui::Button *revert = ui::uiDefIconButO(block,
                                               ui::ButtonType::But,
                                               "MIXIE_OT_revert_prompt",
                                               blender::wm::OpCallContext::ExecDefault,
                                               ICON_LOOP_BACK,
                                               refine_x,
                                               refine_y,
                                               refine_w,
                                               generate_h,
                                               nullptr);
        ui::mixar_style_button(
            revert, ui::MixarComponent::Action, ui::MixarVariant::Secondary, UI_SCALE_FAC * 0.65f);
        RNA_string_set(ui::button_operator_ptr_ensure(revert), "node_id", node_id);
        moodboard_set_node_tooltip(
            revert, "Revert\n\nRestore the prompt you wrote before it was refined.");
        refine_x -= refine_gap + refine_w;
      }

      ui::Button *refine = ui::uiDefIconButO(block,
                                             ui::ButtonType::But,
                                             "MIXIE_OT_refine_prompt",
                                             blender::wm::OpCallContext::ExecDefault,
                                             ICON_SHADERFX,
                                             refine_x,
                                             refine_y,
                                             refine_w,
                                             generate_h,
                                             nullptr);
      ui::mixar_style_button(
          refine, ui::MixarComponent::Action, ui::MixarVariant::Secondary, UI_SCALE_FAC * 0.65f);
      RNA_string_set(ui::button_operator_ptr_ensure(refine), "node_id", node_id);
      /* Refine survives its own success: a rewrite that missed is as often
       * answered by running it again as by taking the original back, and
       * Revert always returns the user's OWN words however many passes ran. */
      moodboard_set_node_tooltip(refine,
                                 refined ?
                                     "Refine Again\n\nRewrite this prompt once more for the "
                                     "model it will be sent to. Revert still restores your "
                                     "own wording, not the previous refinement." :
                                     "Refine\n\nRewrite this prompt for the model it will be "
                                     "sent to, adding the detail that model responds to.");
      /* After the tooltip, so the disabled hint is what the reader gets
       * first when the button cannot be pressed. The button stays in place
       * rather than disappearing, so Generate does not shift sideways under
       * the pointer as the prompt is typed. */
      const bool has_prompt = RNA_string_length(node, "prompt") > 0;
      if (!has_prompt || refining) {
        ui::button_disable(refine, refining ? "Refining this prompt..." : "Write a prompt first");
      }
    }

    /* ASSEMBLE (append-only action index 11) runs locally: it queues nothing,
     * so it must not inherit the run operator's "add to the queue" tooltip. */
    const bool assemble = RNA_enum_get(node, "action_type") == 11;
    const char *run_label = assemble ? "Assemble" : "Generate";
    ui::Button *generate = ui::uiDefButO(block,
                                         ui::ButtonType::But,
                                         "MIXIE_OT_moodboard_run_action_node",
                                         blender::wm::OpCallContext::ExecDefault,
                                         run_label,
                                         tile.xmax - margin - generate_w,
                                         tile.ymin + margin,
                                         generate_w,
                                         generate_h,
                                         nullptr);
    ui::mixar_style_button(generate, ui::MixarComponent::Action,
                          ui::MixarVariant::Primary, UI_SCALE_FAC * 0.65f);
    RNA_string_set(ui::button_operator_ptr_ensure(generate), "node_id", node_id);
    if (assemble) {
      moodboard_set_node_tooltip(generate,
                                 "Assemble\n\nAttach the connected parts to the body, "
                                 "locally. Uses no credits.");
    }
  }
}

}  // namespace blender::ed::mixie
