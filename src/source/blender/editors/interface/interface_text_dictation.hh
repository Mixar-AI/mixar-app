/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once

#include <string>

struct bContext;
struct wmEvent;
struct wmWindow;
struct wmWindowManager;

namespace blender {
struct wmTimer;
}

namespace blender::ui {
struct Button;

/** Owned by a single native text-edit lifetime, never by an RNA pointer cache. */
struct TextDictation {
  wmTimer *timer = nullptr;
  std::string token;
  std::string base;
  int cursor = 0, selection_start = 0, selection_end = 0;
  bool started = false;
  bool chat_target = false;
  bool released = false;
  bool suppress_repeats = false;
  std::string displayed_status;
};

struct TextDictationEvent {
  bool handled = false;
  std::string insert;
};

TextDictationEvent text_dictation_event(bContext *C,
                                        Button *but,
                                        TextDictation &state,
                                        const wmEvent *event,
                                        bool ime_composing,
                                        bool multiline);
void text_dictation_end(bContext *C,
                        wmWindowManager *wm,
                        wmWindow *window,
                        TextDictation &state);
}  // namespace blender::ui
