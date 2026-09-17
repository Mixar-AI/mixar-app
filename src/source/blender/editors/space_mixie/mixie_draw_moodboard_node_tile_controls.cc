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

#include "BLI_string.h"
#include "BLI_time.h"

#include "ED_mixar_audio.hh"
#include "ED_mixar_audio_ui.hh"

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

void moodboard_add_node_tile_controls(const bContext *C,
                                      uiBlock *block,
                                      PointerRNA *node,
                                      const rctf &node_rect,
                                      const bool generation_running,
                                      const bool has_result,
                                      const int state,
                                      const bool edit_mode,
                                      const char *node_id,
                                      blender::Vector<VoiceButtonDraw> &voice_buttons)
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

    const int generate_x = int(node_rect.xmax) - prompt_margin - generate_w;

    /* The prompt's own controls, on the row beneath it.
     *
     * TWO features meet here and they are deliberately not interleaved.
     * Refine / Revert TRANSFORM text that is already written, so they run
     * right-to-left from Generate, the action they lead to; the mic FILLS the
     * field, so it is anchored to the tile's LEFT edge. That is the same split
     * the sidebar makes, where the mic rides the prompt header and
     * Refine / Revert sits under the field — one control group per side of the
     * thing they act on, rather than three similar buttons in a row.
     *
     * It also keeps both groups still. Generate never moves, and because the
     * mic is ANCHORED rather than queued behind the pair, it does not slide
     * sideways when Revert appears after a refinement — a control that jumps
     * under a reaching pointer is worse than one that is further away.
     *
     * Only when the node takes a prompt: a mesh-only node has no text field
     * for any of this to act on. */
    if (RNA_boolean_get(node, "show_prompt")) {
      const int row_y = int(node_rect.ymin) + prompt_margin;
      /* Square, like the card's floating action row, so every icon control on
       * a node is the same target size. */
      const int control_w = generate_h;
      const int control_gap = int(8 * UI_SCALE_FAC);

      /* -- Refine / Revert, right to left from Generate -------------------- */

      const bool refined = RNA_boolean_get(node, "prompt_refined");
      const bool refining = RNA_boolean_get(node, "prompt_refining");
      int refine_x = generate_x - control_gap - control_w;

      if (refined) {
        uiBut *revert = uiDefIconButO(block,
                                      ButType::But,
                                      "MIXIE_OT_revert_prompt",
                                      blender::wm::OpCallContext::ExecDefault,
                                      ICON_LOOP_BACK,
                                      refine_x,
                                      row_y,
                                      control_w,
                                      generate_h,
                                      nullptr);
        RNA_string_set(UI_but_operator_ptr_ensure(revert), "node_id", node_id);
        moodboard_set_node_tooltip(
            revert,
            "Revert\n\nRestore the prompt you wrote before it was refined.");
        refine_x -= control_gap + control_w;
      }

      uiBut *refine = uiDefIconButO(block,
                                    ButType::But,
                                    "MIXIE_OT_refine_prompt",
                                    blender::wm::OpCallContext::ExecDefault,
                                    ICON_SHADERFX,
                                    refine_x,
                                    row_y,
                                    control_w,
                                    generate_h,
                                    nullptr);
      RNA_string_set(UI_but_operator_ptr_ensure(refine), "node_id", node_id);
      /* Refine survives its own success: a rewrite that missed is as often
       * answered by running it again as by taking the original back, and
       * Revert always returns the user's OWN words however many passes ran. */
      moodboard_set_node_tooltip(
          refine,
          refined ? "Refine Again\n\nRewrite this prompt once more for the "
                    "model it will be sent to. Revert still restores your "
                    "own wording, not the previous refinement."
                  : "Refine\n\nRewrite this prompt for the model it will be "
                    "sent to, adding the detail that model responds to.");
      /* After the tooltip, so the disabled hint is what the reader gets
       * first when the button cannot be pressed. The button stays in place
       * rather than disappearing, so Generate does not shift sideways under
       * the pointer as the prompt is typed. */
      const bool has_prompt = RNA_string_length(node, "prompt") > 0;
      if (!has_prompt || refining) {
        UI_but_disable(refine,
                       refining ? "Refining this prompt..." :
                                  "Write a prompt first");
      }

      /* -- Mic, anchored to the tile's left edge --------------------------- */

      const int mic_x = int(node_rect.xmin) + prompt_margin;
      /* A card narrow enough to run the two groups together drops the MIC, not
       * the refine pair: Refine sits beside the Generate it feeds and has no
       * other home on this card, while dictation is reachable again the moment
       * the card is widened. Overlapping widgets would leave both unusable. */
      if (mic_x + control_w + control_gap <= refine_x) {
        /* The SAME hand-drawn glyph the chat composer and the Agent Bubble
         * use — `ED_mixar_voice_draw_button`, recorded here and painted once
         * the block is drawn. A mic is one control that happens to appear in
         * four places, so it reads and animates identically in all of them:
         * the level-driven halo while recording, the stop square, the spun arc
         * while transcribing. An `ICON_*` can do none of that.
         *
         * The button is label-less for the same reason the composer's is: it
         * owns the click, the hover plate and the tooltip, while the glyph
         * goes on top. */
        const MixarVoiceVisual voice = ED_mixar_voice_visual_state(C);
        /* `node:` plus the id, sized off the same buffer every graph
         * string read uses (mixie_intern.hh). */
        char voice_target[MIXIE_GRAPH_ID_BUF + 8];
        BLI_snprintf(voice_target, sizeof(voice_target), "node:%s", node_id);
        /* Recording elsewhere must not make THIS node's mic look live. */
        const bool mine = ED_mixar_voice_target_is(C, voice_target);

        uiBut *mic = uiDefButO(block,
                               ButType::But,
                               "MIXAR_OT_voice_record_toggle",
                               blender::wm::OpCallContext::ExecDefault,
                               "",
                               mic_x,
                               row_y,
                               control_w,
                               generate_h,
                               nullptr);
        /* Scoped to THIS node: the transcript lands in the prompt the user was
         * standing in, even if another card is selected while it transcribes. */
        RNA_string_set(UI_but_operator_ptr_ensure(mic), "target", voice_target);
        moodboard_set_node_tooltip(
            mic,
            mine && voice == MixarVoiceVisual::Recording ?
                "Stop dictating\n\nStop recording and add what you said to "
                "this node's prompt." :
                "Dictate\n\nRecord your voice and add the transcript to this "
                "node's prompt. Press again to stop.");

        VoiceButtonDraw paint;
        paint.rect.xmin = float(mic_x);
        paint.rect.xmax = float(mic_x + control_w);
        paint.rect.ymin = float(row_y);
        paint.rect.ymax = float(row_y + generate_h);
        paint.state = mine ? voice : MixarVoiceVisual::Idle;
        voice_buttons.append(paint);
      }
    }

    uiBut *generate = uiDefButO(block,
                                ButType::But,
                                "MIXIE_OT_moodboard_run_action_node",
                                blender::wm::OpCallContext::ExecDefault,
                                "Generate",
                                generate_x,
                                int(node_rect.ymin) + prompt_margin,
                                generate_w,
                                generate_h,
                                nullptr);
    RNA_string_set(UI_but_operator_ptr_ensure(generate), "node_id", node_id);
  }
}

void moodboard_draw_voice_buttons(const blender::Vector<VoiceButtonDraw> &voice_buttons)
{
  if (voice_buttons.is_empty()) {
    return;
  }
  /* Sampled ONCE for the whole pass. The painter deliberately reads neither,
   * so that two mics drawn in one frame cannot show two different levels for
   * the single recording behind them. The level comes straight from the
   * capture engine rather than through RNA: this is a draw pass and the
   * engine's reading is an atomic load. */
  const float level = ED_mixar_audio_level();
  const float pulse = float(BLI_time_now_seconds());

  for (const VoiceButtonDraw &voice : voice_buttons) {
    /* `hovered` is false: the label-less button underneath already draws the
     * widget system's own hover plate, and a second one painted on top of it
     * would read as a double highlight. */
    ED_mixar_voice_draw_button(&voice.rect, voice.state, level, pulse, false);
  }
}

}  // namespace blender::ed::mixie
