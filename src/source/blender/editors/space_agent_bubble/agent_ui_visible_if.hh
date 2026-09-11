/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Catalog `visible_if` table carried on generated param groups
 * (`mixar_visible_if`). RNA-free so standalone tests can compile it.
 * Keys are RNA attributes (`p_*`), never hardcoded catalog names.
 */

#pragma once

#include <iomanip>
#include <limits>
#include <locale>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace blender {

inline constexpr const char *PANE_VISIBLE_IF_ATTR = "mixar_visible_if";
inline constexpr const char *PANE_VISIBLE_IF_MISSING = "__missing__";

struct MixarVisibleIfTable {
  std::unordered_map<std::string, std::vector<std::pair<std::string, std::string>>> by_attr;
};

namespace visible_if_detail {

/** Same as Python format(double, ".17g"), independent of the UI locale. */
inline std::string float_string(const float value)
{
  std::ostringstream out;
  out.imbue(std::locale::classic());
  out << std::setprecision(std::numeric_limits<double>::max_digits10) << double(value);
  return out.str();
}

struct Cursor {
  std::string_view s;
  size_t i = 0;

  void skip()
  {
    while (i < s.size() && (s[i] == ' ' || s[i] == '\n' || s[i] == '\r' || s[i] == '\t')) {
      i++;
    }
  }
  bool eat(const char c)
  {
    skip();
    if (i < s.size() && s[i] == c) {
      i++;
      return true;
    }
    return false;
  }
};

inline bool hex4(Cursor &c, unsigned &r_code)
{
  if (c.i + 4 > c.s.size()) {
    return false;
  }
  unsigned code = 0;
  for (int k = 0; k < 4; k++) {
    const char h = c.s[c.i++];
    code <<= 4;
    if (h >= '0' && h <= '9') {
      code += unsigned(h - '0');
    }
    else if (h >= 'a' && h <= 'f') {
      code += 10u + unsigned(h - 'a');
    }
    else if (h >= 'A' && h <= 'F') {
      code += 10u + unsigned(h - 'A');
    }
    else {
      return false;
    }
  }
  r_code = code;
  return true;
}

inline void utf8(std::string &out, const unsigned code)
{
  if (code < 0x80) {
    out.push_back(char(code));
  }
  else if (code < 0x800) {
    out.push_back(char(0xC0 | (code >> 6)));
    out.push_back(char(0x80 | (code & 0x3F)));
  }
  else if (code < 0x10000) {
    out.push_back(char(0xE0 | (code >> 12)));
    out.push_back(char(0x80 | ((code >> 6) & 0x3F)));
    out.push_back(char(0x80 | (code & 0x3F)));
  }
  else {
    out.push_back(char(0xF0 | (code >> 18)));
    out.push_back(char(0x80 | ((code >> 12) & 0x3F)));
    out.push_back(char(0x80 | ((code >> 6) & 0x3F)));
    out.push_back(char(0x80 | (code & 0x3F)));
  }
}

inline bool parse_string(Cursor &c, std::string &out)
{
  c.skip();
  if (c.i >= c.s.size() || c.s[c.i] != '"') {
    return false;
  }
  c.i++;
  out.clear();
  while (c.i < c.s.size()) {
    const char ch = c.s[c.i++];
    if (ch == '"') {
      return true;
    }
    if (ch == '\\') {
      if (c.i >= c.s.size()) {
        return false;
      }
      const char e = c.s[c.i++];
      switch (e) {
        case '"':
        case '\\':
        case '/':
          out.push_back(e);
          break;
        case 'n':
          out.push_back('\n');
          break;
        case 'r':
          out.push_back('\r');
          break;
        case 't':
          out.push_back('\t');
          break;
        case 'b':
          out.push_back('\b');
          break;
        case 'f':
          out.push_back('\f');
          break;
        case 'u': {
          unsigned code = 0;
          if (!hex4(c, code)) {
            return false;
          }
          if (code >= 0xD800 && code <= 0xDBFF) {
            unsigned low = 0;
            if (c.i + 2 > c.s.size() || c.s[c.i++] != '\\' || c.s[c.i++] != 'u' ||
                !hex4(c, low) || low < 0xDC00 || low > 0xDFFF)
            {
              return false;
            }
            code = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00);
          }
          else if (code >= 0xDC00 && code <= 0xDFFF) {
            return false;
          }
          utf8(out, code);
          break;
        }
        default:
          return false;
      }
    }
    else if (static_cast<unsigned char>(ch) < 0x20) {
      return false;
    }
    else {
      out.push_back(ch);
    }
  }
  return false;
}

inline bool parse_inner(Cursor &c, std::vector<std::pair<std::string, std::string>> &r_pairs)
{
  if (!c.eat('{')) {
    return false;
  }
  r_pairs.clear();
  c.skip();
  if (c.eat('}')) {
    return true;
  }
  while (true) {
    std::string key;
    std::string value;
    if (!parse_string(c, key) || !c.eat(':') || !parse_string(c, value)) {
      return false;
    }
    r_pairs.emplace_back(std::move(key), std::move(value));
    c.skip();
    if (c.eat('}')) {
      return true;
    }
    if (!c.eat(',')) {
      return false;
    }
  }
}

}  // namespace visible_if_detail

inline bool pane_visible_if_parse(std::string_view json, MixarVisibleIfTable &r_out)
{
  r_out = {};
  visible_if_detail::Cursor c{json, 0};
  c.skip();
  if (c.i >= c.s.size()) {
    return true;
  }
  if (!c.eat('{')) {
    return false;
  }
  c.skip();
  if (c.eat('}')) {
    c.skip();
    return c.i >= c.s.size();
  }
  while (true) {
    std::string attr;
    std::vector<std::pair<std::string, std::string>> pairs;
    if (!visible_if_detail::parse_string(c, attr) || !c.eat(':') ||
        !visible_if_detail::parse_inner(c, pairs))
    {
      return false;
    }
    r_out.by_attr[std::move(attr)] = std::move(pairs);
    c.skip();
    if (c.eat('}')) {
      c.skip();
      return c.i >= c.s.size();
    }
    if (!c.eat(',')) {
      return false;
    }
  }
}

template<typename Read>
inline bool pane_visible_if_matches(const MixarVisibleIfTable &table,
                                    std::string_view prop_id,
                                    Read &&read_py_str)
{
  const auto it = table.by_attr.find(std::string(prop_id));
  if (it == table.by_attr.end()) {
    return true;
  }
  for (const auto &[other, expected] : it->second) {
    const std::optional<std::string> current = read_py_str(std::string_view(other));
    if (!current || *current != expected) {
      return false;
    }
  }
  return true;
}

}  // namespace blender
