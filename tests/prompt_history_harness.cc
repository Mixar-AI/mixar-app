/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** Compile against the shipped navigation header only — no Mixar binary.
 *
 *   c++ -std=c++17 -I src/source/blender/editors/space_mixie_chat \
 *       tests/prompt_history_harness.cc -o prompt_history_harness
 *
 * Reads a script on stdin, one command per line, and plays it against one
 * PromptHistoryCursor the way interface_handlers.cc does:
 *
 *   prompts a|b|c    the chat's sent prompts, newest first
 *   composer NAME    which composer (scene) the next keys go to
 *   type TEXT        the composer now holds TEXT (an edit)
 *   up / down        one key; prints "changed<TAB>text" or "same<TAB>text"
 *   clip N           the composer keeps only N bytes of what was shown
 */

#include "mixie_chat_prompt_history.hh"

#include <cstdio>
#include <iostream>
#include <map>
#include <string>
#include <vector>

int main()
{
  blender::mixie_chat::PromptHistoryCursor cursor;
  std::vector<std::string> prompts;
  std::map<std::string, int> composers;
  const void *composer = &composers["A"];
  std::string text;

  std::string line;
  while (std::getline(std::cin, line)) {
    const size_t space = line.find(' ');
    const std::string command = line.substr(0, space);
    const std::string arg = (space == std::string::npos) ? "" : line.substr(space + 1);
    if (command == "prompts") {
      prompts.clear();
      size_t start = 0;
      while (!arg.empty() && start <= arg.size()) {
        const size_t bar = arg.find('|', start);
        prompts.push_back(arg.substr(start, bar - start));
        if (bar == std::string::npos) {
          break;
        }
        start = bar + 1;
      }
    }
    else if (command == "composer") {
      composer = &composers[arg];
    }
    else if (command == "type") {
      text = arg;
    }
    else if (command == "clip") {
      text = text.substr(0, std::stoul(arg));
      cursor.landed(text);
    }
    else if (command == "up" || command == "down") {
      const std::optional<std::string> next = (command == "up") ?
                                                  cursor.older(composer, text, prompts) :
                                                  cursor.newer(composer, text, prompts);
      if (next) {
        text = *next;
        cursor.landed(text);
      }
      std::printf("%s\t%s\n", next ? "changed" : "same", text.c_str());
    }
    else {
      std::fprintf(stderr, "unknown command: %s\n", line.c_str());
      return 2;
    }
  }
  return 0;
}
