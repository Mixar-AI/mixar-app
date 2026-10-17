/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Line breaking shared by every chat text path (mixie_chat_line_break.cc).
 */

#pragma once

#include <string>

#include "BLF_enums.hh"
#include "BLI_string_ref.hh"
#include "BLI_vector.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* Prose wrap for the chat's BLF text paths: Typographical breaks inside
 * Chinese and Japanese (which have no spaces) and HardLimit folds an
 * unbreakable token at the edge. Minimal wrapped on ASCII spaces only, so a
 * Japanese reply ran past the bubble's right edge. Measure, draw and the
 * selection mapping must all use it. */
constexpr BLFWrapMode CHAT_PROSE_WRAP = BLFWrapMode(int(BLFWrapMode::Typographical) |
                                                    int(BLFWrapMode::HardLimit));

/* Line-break units for chat_ui_rich_text: the byte offset where the unit
 * starting at `start` ends — at whitespace, or at a break opportunity next to
 * a CJK character (kinsoku-aware). Always advances at least one character. */
int chat_ui_line_unit_end(const char *buf, int start, int len);

/* Kinsoku for a soft line break the BLF wrapper chose: the line runs from
 * `line_start` to `brk` and the next starts at `brk` with nothing dropped
 * between. Returns `brk`, or an earlier break so that no line starts with a
 * closer (。、」, small kana, ー) or ends with an opener (「（): the preceding
 * character moves down with it. Never empties the line. */
int chat_ui_kinsoku_break(const char *buf, int line_start, int brk, int len);

/* Byte length of the UTF-8 character at `buf[i]` (1 for a malformed byte). */
int chat_ui_utf8_char_size(const char *buf, int i, int len);

/* BLF_string_wrap with kinsoku applied to CHAT_PROSE_WRAP (other modes pass
 * through). Lines point into `text`. Returns true when a break moved. The
 * caller sets the font size and flags first (mixie_chat_prose_wrap.cc). */
bool chat_ui_wrap_lines(int font_id,
                        const char *text,
                        int width,
                        BLFWrapMode mode,
                        Vector<StringRef> &r_lines);

/* The string to hand BLF's wrapped draw/measure: `text` itself, or (when
 * kinsoku moved a break) its lines joined by newlines in `r_storage`. */
const char *chat_ui_prose_text(
    int font_id, const char *text, int width, BLFWrapMode mode, std::string &r_storage);

}  // namespace blender
