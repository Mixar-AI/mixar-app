/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Prompt recall for the chat composer: the RNA side of
 * mixie_chat_prompt_history.hh.
 *
 * The prompts are the USER messages already in `scene.mixie_chat_messages`,
 * so the list follows the chat on screen: each scene tab has its own, a
 * loaded session brings its own and a new session starts empty. No second
 * copy of what was sent is kept anywhere.
 */

#include <algorithm>
#include <optional>
#include <string>
#include <vector>

#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "DNA_scene_types.h"

#include "RNA_access.hh"

#include "mixie_chat_prompt_history.hh"

namespace blender {

/* One composer is edited at a time; the cursor remembers which one. */
static mixie_chat::PromptHistoryCursor g_prompt_history;

static bool prompt_history_message_is_user(PointerRNA *message)
{
  PropertyRNA *prop = RNA_struct_find_property(message, "sender");
  if (!prop || RNA_property_type(prop) != PROP_ENUM) {
    return false;
  }
  const char *identifier = nullptr;
  return RNA_property_enum_identifier(
             nullptr, message, prop, RNA_property_enum_get(message, prop), &identifier) &&
         identifier && STREQ(identifier, "USER");
}

static std::string prompt_history_string(PointerRNA *message, const char *name)
{
  PropertyRNA *prop = RNA_struct_find_property(message, name);
  if (!prop || RNA_property_type(prop) != PROP_STRING) {
    return {};
  }
  return RNA_property_string_get(message, prop);
}

/** The user's messages in this chat, newest first. Repeats in a row collapse to one. */
static std::vector<std::string> prompt_history_collect(Scene *scene)
{
  std::vector<std::string> prompts;
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *messages = RNA_struct_find_property(&scene_ptr, "mixie_chat_messages");
  if (!messages || RNA_property_type(messages) != PROP_COLLECTION) {
    return prompts;
  }
  CollectionPropertyIterator iter;
  RNA_property_collection_begin(&scene_ptr, messages, &iter);
  for (; iter.valid; RNA_property_collection_next(&iter)) {
    PointerRNA message = iter.ptr;
    if (!prompt_history_message_is_user(&message)) {
      continue;
    }
    /* Restored history can carry a user message in `content` instead (the
     * same fallback chat_history.py uses for session titles). */
    std::string text = prompt_history_string(&message, "text");
    if (text.empty()) {
      text = prompt_history_string(&message, "content");
    }
    /* An image-only message has no words to recall. */
    if (text.empty() || (!prompts.empty() && prompts.back() == text)) {
      continue;
    }
    prompts.push_back(std::move(text));
  }
  RNA_property_collection_end(&iter);
  std::reverse(prompts.begin(), prompts.end());
  return prompts;
}

bool mixie_chat_prompt_history_step(Scene *scene,
                                    const char *current,
                                    const int direction,
                                    std::string &r_text)
{
  if (!scene || !current) {
    return false;
  }
  const std::vector<std::string> prompts = prompt_history_collect(scene);
  std::optional<std::string> text = (direction < 0) ?
                                        g_prompt_history.older(scene, current, prompts) :
                                        g_prompt_history.newer(scene, current, prompts);
  if (!text) {
    return false;
  }
  r_text = std::move(*text);
  return true;
}

void mixie_chat_prompt_history_landed(const char *text)
{
  g_prompt_history.landed(text ? text : "");
}

}  // namespace blender
