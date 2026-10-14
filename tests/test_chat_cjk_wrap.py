# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Chinese and Japanese chat text has no spaces, so the chat must break
between CJK characters or a reply runs past the bubble's right edge.

The production line-break units are compiled and run; the BLF wrap paths are
pinned to the typographical mode at the source level.
"""

from pathlib import Path
import re
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "src/source/blender/editors/space_mixie_chat"
STUBS = {
    "BLF_enums.hh": r'''
#pragma once
enum class BLFWrapMode : int { Minimal = 0, Typographical = 1, Path = 2, HardLimit = 4 };
''',
    "BLI_string_ref.hh": r'''
#pragma once
#include <cstdint>
#include <cstring>
namespace blender {
class StringRef {
  const char *d_ = nullptr;
  int64_t n_ = 0;
 public:
  StringRef() = default;
  StringRef(const char *s) : d_(s), n_(int64_t(strlen(s))) {}
  StringRef(const char *s, int64_t n) : d_(s), n_(n) {}
  const char *data() const { return d_; }
  int64_t size() const { return n_; }
};
}
''',
    "BLI_vector.hh": r'''
#pragma once
#include <cstdint>
#include <vector>
namespace blender {
template<class T> struct Vector : std::vector<T> {
  void append(const T &v) { this->push_back(v); }
  int64_t size() const { return int64_t(std::vector<T>::size()); }
};
}
''',
    "BLF_api.hh": r'''
#pragma once
#include "BLF_enums.hh"
#include "BLI_string_ref.hh"
#include "BLI_vector.hh"
namespace blender {
Vector<StringRef> BLF_string_wrap(int fontid, StringRef str, int width, BLFWrapMode mode);
}
''',
}


def _compile(tmp_path, name, body, extra=()):
    compiler = shutil.which("c++") or shutil.which("clang++")
    assert compiler
    for header, text in STUBS.items():
        (tmp_path / header).write_text(text)
    source = tmp_path / f"{name}.cc"
    source.write_text(body)
    binary = tmp_path / name
    subprocess.run(
        [compiler, "-std=c++17", "-I", str(tmp_path), "-I", str(CHAT), str(source),
         str(CHAT / "mixie_chat_line_break.cc"), *[str(CHAT / e) for e in extra],
         "-o", str(binary)],
        check=True,
    )
    return binary


def _units(tmp_path, cases):
    literals = ",".join('u8"' + c + '"' for c in cases)
    binary = _compile(tmp_path, "units", r'''
#include <cstdio>
#include <cstring>
#include "mixie_chat_line_break.hh"
int main() {
  const char *cases[] = {''' + literals + r'''};
  for (const char *s : cases) {
    const int n = int(strlen(s));
    for (int i = 0; i < n;) {
      if (s[i] == ' ') { i++; continue; }
      const int e = blender::chat_ui_line_unit_end(s, i, n);
      printf("[%.*s]", e - i, s + i);
      i = e;
    }
    printf("\n");
  }
}
''')
    out = subprocess.run([str(binary)], check=True, capture_output=True)
    return out.stdout.decode("utf-8").splitlines()


def test_cjk_prose_breaks_between_characters_and_respects_kinsoku(tmp_path):
    lines = _units(tmp_path, [
        "日本語のテキスト。",
        "「こんにちは」と言った。",
        "ちょっとまって",
        "Blenderでモデル",
        "hello world foo_bar",
        "https://example.com/a/long/path",
    ])
    assert lines == [
        "[日][本][語][の][テ][キ][ス][ト。]",
        # Opening brackets stay with what follows, closers, small kana and
        # full stops stay with what precedes.
        "[「こ][ん][に][ち][は」][と][言っ][た。]",
        "[ちょっ][と][まっ][て]",
        "[Blender][で][モ][デ][ル]",
        "[hello][world][foo_bar]",
        "[https://example.com/a/long/path]",
    ]


def test_truncated_utf8_still_advances(tmp_path):
    # rt_parse can cut its buffer mid-character; a stray lead byte must not
    # stall the layout loop.
    binary = _compile(tmp_path, "trunc", r'''
#include "mixie_chat_line_break.hh"
int main() {
  const char s[] = {'a', char(0xE6), char(0x97), 0};
  return blender::chat_ui_line_unit_end(s, 0, 3) == 3 &&
         blender::chat_ui_line_unit_end(s, 1, 3) > 1 ? 0 : 1;
}
''')
    assert subprocess.run([str(binary)]).returncode == 0


# BLF's typographical wrap may break after any CJK character. The fake below
# does exactly that (a break every `width` characters), so the production
# kinsoku pass is exercised on the breaks BLF really produces.
FAKE_BLF_WRAP = r'''
#include <cstdio>
#include <cstring>
#include "BLF_api.hh"
#include "mixie_chat_line_break.hh"
namespace blender {
Vector<StringRef> BLF_string_wrap(int, StringRef str, int width, BLFWrapMode) {
  Vector<StringRef> lines;
  const char *p = str.data(), *end = str.data() + str.size(), *start = p;
  int chars = 0;
  while (p < end) {
    const int size = chat_ui_utf8_char_size(p, 0, int(end - p));
    if (chars == width) { lines.append(StringRef(start, p - start)); start = p; chars = 0; }
    p += size;
    chars++;
  }
  lines.append(StringRef(start, p - start));
  return lines;
}
}
'''


def _wrapped(tmp_path, cases, width):
    literals = ",".join('u8"' + c + '"' for c in cases)
    binary = _compile(tmp_path, "wrap", FAKE_BLF_WRAP + r'''
int main() {
  const char *cases[] = {''' + literals + r'''};
  for (const char *s : cases) {
    blender::Vector<blender::StringRef> lines;
    blender::chat_ui_wrap_lines(0, s, ''' + str(width) + r''', blender::CHAT_PROSE_WRAP, lines);
    for (const auto &l : lines) printf("[%.*s]", int(l.size()), l.data());
    std::string storage;
    printf(" %s\n", blender::chat_ui_prose_text(0, s, ''' + str(width) + r''',
                                                  blender::CHAT_PROSE_WRAP, storage) == s ?
                         "same" : "joined");
  }
}
''', extra=("mixie_chat_prose_wrap.cc",))
    out = subprocess.run([str(binary)], check=True, capture_output=True)
    return out.stdout.decode("utf-8").splitlines()


def test_closing_punctuation_never_starts_a_wrapped_line(tmp_path):
    """QA on #1834: a plain bubble's final 。 could sit alone on its own line."""
    assert _wrapped(tmp_path, [
        "これはテストです。",
        "「あいう」えお",
        "あいうえっお",
        "あいうえおかきくけ",
        "。。。。。。",
    ], 4) == [
        # The character before a closer moves down with it.
        "[これはテ][ストで][す。] joined",
        "[「あい][う」えお] joined",
        # Small kana stay with what precedes them.
        "[あいう][えっお] joined",
        # Nothing to fix: BLF's own lines, drawn from the original string.
        "[あいうえ][おかきく][け] same",
        # A run of closers cannot be fixed without emptying a line.
        "[。。。。][。。] same",
    ]


def test_rich_text_uses_cjk_units_and_folds_long_tokens():
    source = (CHAT / "mixie_chat_ui_rich_text.cc").read_text(encoding="utf-8")
    body = source[source.index("float chat_ui_rich_text("):]
    assert "chat_ui_line_unit_end(buf, i, n)" in body
    assert "rt_fit_prefix(" in body
    # The old space-only word scan is gone.
    assert "while (i < n && buf[i] != ' '" not in body


def test_blf_chat_paths_wrap_typographically():
    header = (CHAT / "mixie_chat_line_break.hh").read_text(encoding="utf-8")
    assert re.search(r"CHAT_PROSE_WRAP\s*=\s*BLFWrapMode\(int\(BLFWrapMode::Typographical\) \|",
                     header)
    for path in CHAT.glob("*.[ch]*"):
        text = path.read_text(encoding="utf-8")
        assert "BLFWrapMode::Minimal" not in text, path.name
        # A bare BLF_wordwrap(font, width) defaults to Minimal.
        assert not re.search(r"BLF_wordwrap\([^,()]+,\s*int\([^()]*\)\)", text), path.name
