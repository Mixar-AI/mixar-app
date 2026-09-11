/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

namespace blender::ui {

/** Semantic roles for explicitly drawn Mixar text. Native RNA text keeps its
 * own font metrics so caret, selection, number formatting and IME stay native. */
enum class MixarTextRole { Body, Caption, Heading, Prompt, ListTitle, ListMeta };

/** Artboard sizes, not pixels. List roles preserve the larger type needed by
 * two-line result rows; they are not a different UI scale or density. */
constexpr float mixar_text_role_size(const MixarTextRole role)
{
  switch (role) {
    case MixarTextRole::Body:
      return 18.0f;
    case MixarTextRole::Caption:
      return 15.0f;
    case MixarTextRole::Heading:
      return 25.0f;
    case MixarTextRole::Prompt:
      return 24.0f;
    case MixarTextRole::ListTitle:
      return 23.0f;
    case MixarTextRole::ListMeta:
      return 19.0f;
  }
  return 18.0f;
}

/** Resolve the host unit once, then pass this same value to measurement,
 * fitting and drawing. No implicit conversion to float or second scale step. */
struct MixarTextStyle {
  float size;
};
constexpr MixarTextStyle mixar_text_style(const MixarTextRole role, const float host_unit)
{
  return {mixar_text_role_size(role) * host_unit};
}

}  // namespace blender::ui
