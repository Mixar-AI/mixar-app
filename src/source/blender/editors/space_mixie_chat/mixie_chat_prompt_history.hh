/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Shell-style prompt recall for the chat composer: Up on the composer's top
 * line shows the previous message the user sent in this chat, Down on its
 * bottom line walks forward and finally restores the draft that was there
 * before the first Up.
 *
 * Standard-library only, so the navigation rules stay readable apart from the
 * RNA glue in mixie_chat_prompt_history.cc.
 */

#pragma once

#include <algorithm>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace blender::mixie_chat {

struct PromptHistoryCursor {
  /** Composer that owns the walk (its Scene); another composer starts over. */
  const void *owner = nullptr;
  /** Position in the newest-first prompt list; -1 is the user's own draft. */
  int index = -1;
  /** What the composer held before the first Up. */
  std::string draft;
  /** What the last step put in the composer. Editing it ends the walk. */
  std::string shown;

  bool browsing(const void *composer, std::string_view current) const
  {
    return index >= 0 && owner == composer && current == shown;
  }

  /** Up: the next older prompt, or nothing when there is none. */
  std::optional<std::string> older(const void *composer,
                                   std::string_view current,
                                   const std::vector<std::string> &prompts)
  {
    if (!browsing(composer, current)) {
      owner = composer;
      index = -1;
      draft = current;
    }
    int next = index + 1;
    /* A prompt identical to the text already shown would look like a no-op. */
    while (next < int(prompts.size()) && prompts[next] == current) {
      next++;
    }
    if (next >= int(prompts.size())) {
      return std::nullopt;
    }
    index = next;
    shown = prompts[next];
    return shown;
  }

  /** Down: the next newer prompt, then the saved draft. Nothing when not walking. */
  std::optional<std::string> newer(const void *composer,
                                   std::string_view current,
                                   const std::vector<std::string> &prompts)
  {
    if (!browsing(composer, current)) {
      return std::nullopt;
    }
    /* The transcript can shrink mid-walk (a new session clears it). */
    const int next = std::min(index, int(prompts.size())) - 1;
    if (next < 0) {
      std::string restored = std::move(draft);
      reset();
      return restored;
    }
    index = next;
    shown = prompts[next];
    return shown;
  }

  /** Record the text the composer actually holds (its max length can clip a long prompt). */
  void landed(std::string_view text)
  {
    if (index >= 0) {
      shown = text;
    }
  }

  void reset()
  {
    owner = nullptr;
    index = -1;
    draft.clear();
    shown.clear();
  }
};

}  // namespace blender::mixie_chat

namespace blender {

struct Scene;

/**
 * Text-edit hooks for `scene.mixie_chat_input`, extern-declared in
 * interface_handlers.cc and called only when Up/Down could not move the
 * cursor further. \param direction: -1 older (Up), +1 newer (Down).
 * \return true when \a r_text holds the text to put in the composer.
 */
bool mixie_chat_prompt_history_step(Scene *scene,
                                    const char *current,
                                    int direction,
                                    std::string &r_text);
/** The text the composer holds after the step was applied. */
void mixie_chat_prompt_history_landed(const char *text);

}  // namespace blender
