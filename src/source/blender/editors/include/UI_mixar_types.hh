/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include <cstdint>
#include <type_traits>

namespace blender::ui {

/** Runtime presentation only: never serialized, never shares storage with RNA
 * values. */
enum class MixarTheme : uint8_t { Native, Zen, LegacyMixar };
/** Host layout density. Default is generation-pane chip spacing; Compact is
 * the denser chrome recipe. Not stored on MixarButtonStyle. */
enum class MixarDensity : uint8_t { Default, Compact };

/** Unscaled artboard spacing. Resolve with mixar_density_metrics. */
struct MixarDensityMetrics {
  float control_height;
  float padding;
  float gap;
  float icon;
  float icon_gap;
  float radius;
};

enum class MixarComponent : uint8_t {
  None,
  Action,
  Dropdown,
  Toggle,
  Input,
  Number,
  Segment,
  Surface,
  Label,
  LegacyCard
};
enum class MixarVariant : uint8_t { Primary, Secondary, Ghost, Danger };

enum class MixarCardElement : uint8_t {
  None = 0,
  /** "Welcome, Rahul !" — oversized, full-contrast. */
  Heading,
  /** "(rahul@mixar.app)" — small, dim. */
  Muted,
  /** "Your Usage" — small, one tier brighter than #Muted so the section
   * reads as a heading rather than as more metadata. */
  SectionLabel,
  /** "4300 of 5000 left" — small, muted, right-aligned. */
  MetaRight,
  /** "PRO Plan" — small bordered chip. */
  Pill,
  /** Full-width quota bar with the percentage inside the fill. */
  UsageBar,
  /** "Buy Credits" — accent-outlined compact button. */
  AccentButton,
  /** Dashboard / AI Provider Settings / Docs — outlined icon buttons. */
  CardButton,
  /** "Report a Bug" — danger-tinted variant of CardButton. */
  DangerButton,
  /** "Logout" — borderless full-width strip. */
  GhostButton,
  /** Horizontal rule between card sections. */
  Divider,
  /** Danger-tinted body text — inline error copy in card-styled dialogs. */
  DangerText,
  /** Topbar mode slider, left half (Zen). Paints the WHOLE two-up track and
   * the animated thumb, then its own label — the right half paints only its
   * label, so the thumb can never cover the left one (buttons draw in
   * creation order). Payload carries the target: 0 = left active, 1 = right. */
  ModeSliderLeft,
  /** Topbar mode slider, right half (Engine): label only. */
  ModeSliderRight,
  /** Topbar "Cinema Mode" pill: dark fill, hairline border, gradient label.
   * Payload is 1.0 while the mode is active. */
  CinemaPill,
  /** Zen viewport shading pill ("Solid" / "Rendered"): the design's dark
   * chip at full opacity when live, 49% when not. Payload is 1.0 for the
   * live one. */
  ViewportPill,
  /** Topbar account chip: dark slab, label left, full-height avatar disc at
   * the right end carrying the stock person glyph. */
  ProfilePill,
  /** Cinema Mode popup row (aspect / lens / output / interpolation lists):
   * the surface's graded row chip when live (payload 1.0), plain dim text
   * otherwise, so a dropdown's list matches the value blocks it opens from.
   * Painted in `interface_mixar_cinema_row.cc`. */
  CinemaRow,
  /** Sentinel — keep last. #UI_mixar_card_element_get range-checks against
   * it, so a kind appended after it would silently read back as None. */
  Count,
};

enum class MixarCinemaRowKind : uint8_t {
  /** An option; a Row (toggle) button lights itself from UI_SELECT. */
  Option = 0,
  /** The current choice: the graded chip. */
  Active = 1,
  /** An action ("Export 2 Keyframes"): white label, hover fill, no chip. */
  Action = 2,
  /** One cell of a segmented group (the lens popup's Perspective /
   * Orthographic / Panoramic): consecutive Segment buttons on one baseline
   * form a group; the hovered cell widens to show its whole label. */
  Segment = 3,
  /** A section caption ("Keyframes", "Render Guides", the shot heading):
   * dim caption text, no chrome. */
  Caption = 4,
  /** A NumSlider: the row-class track with a green fill to the value,
   * label left, value right. */
  Slider = 5,
  /** A Text field laid over text the surface painted itself (My Cameras
   * rename): paints NOTHING while idle; while being edited the chip is
   * painted and the stock text-edit drawing runs on top. */
  Field = 6,
};

enum class MixarCardIcon : uint8_t {
  None = 0,
  /** 2x2 tiles — Dashboard. */
  Grid,
  /** Two tracks with offset knobs — provider/settings. */
  Sliders,
  /** Page outline with text rules — documentation. */
  Document,
  /** Ringed exclamation — report a problem. */
  Alert,
  /** Diagonal cross — sign out. */
  Cross,
};

struct MixarScope {
  MixarTheme theme = MixarTheme::Native;
  bool explicit_theme = false;
  MixarDensity density = MixarDensity::Default;
};

struct MixarButtonStyle {
  MixarComponent component = MixarComponent::None;
  MixarTheme theme = MixarTheme::Native;
  MixarVariant variant = MixarVariant::Primary;
  MixarCardElement card = MixarCardElement::None;
  MixarCinemaRowKind cinema = MixarCinemaRowKind::Option;
  MixarCardIcon icon = MixarCardIcon::None;
  bool lit = false;
  bool explicit_theme = false;
  float progress = 0.0f;
  /** Zero uses native UI metrics. Positive values are already resolved island
   * units. */
  float unit = 0.0f;
};
static_assert(std::is_trivially_copyable_v<MixarButtonStyle>);
static_assert(sizeof(MixarButtonStyle) == 16);

}  // namespace blender::ui
