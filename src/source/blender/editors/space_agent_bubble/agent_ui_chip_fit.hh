/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Pure fitting for the Agent composer's chip row. #agent_chip_forms measures
 * every form of every shown chip with the caller's text measurer
 * (`agent_ui_layout_fit_controls` passes the island font); #agent_chip_fit
 * decides which form each chip takes so the row never runs under Send, at any window
 * width, interface scale or state (Done, Stop, the reading dropdown, a long
 * model name). No Blender headers, so `tests/chip_fit_harness.cc` drives the
 * shipped function across widths and states.
 *
 * Sacrifice order, cheapest first:
 *  1. The model chip walks its own ladder (badge + name, the name elided,
 *     the name alone, the badge) to keep the short "Attach" label readable;
 *     its badge alone may then push Upload toward its icon floor, and
 *     finally it drops.
 *  2. Only when the core chips alone would push Upload below its icon floor
 *     do they shed labels, in #AGENT_CHIP_SHED_ORDER: the live Voice trace
 *     (or the idle "Voice" word), "Auto", "Sketch"/"Done", the reading label,
 *     and last the "Stop" word. Icons, the Auto switch and Send never go.
 */

#pragma once

#include <algorithm>

namespace blender {

enum AgentChipSlot {
  AGENT_CHIP_SLOT_UPLOAD = 0,
  AGENT_CHIP_SLOT_SCRIBBLE,
  AGENT_CHIP_SLOT_VOICE,
  AGENT_CHIP_SLOT_AUTO,
  AGENT_CHIP_SLOT_MODEL,
  AGENT_CHIP_SLOT_READING,
  AGENT_CHIP_SLOT_CLEAR,

  AGENT_CHIP_SLOT_COUNT,
};

inline constexpr int AGENT_CHIP_FORM_MAX = 4;

/** One chip's widths, widest form first (the model chip's in preference
 *  order: a long name's elided form is narrower than its Label, which the
 *  fit then never reaches). `count == 0` means not shown.
 *  Attach uses the same width in both named slots, then its icon floor;
 *  its placed width is continuous between the label and icon. */
struct AgentChipForms {
  float width[AGENT_CHIP_FORM_MAX] = {};
  int count = 0;
};

struct AgentChipFit {
  float width[AGENT_CHIP_SLOT_COUNT] = {}; /* 0 = not placed. */
  int form[AGENT_CHIP_SLOT_COUNT] = {};    /* Index into that chip's forms. */
  bool compact_reference = false;
  /** False only when every chip is already at its floor and still too wide. */
  bool fits = true;
};

/** What the row shows, read from #AgentIslandState by the caller. */
struct AgentChipRowInputs {
  bool scribble_available = false;
  bool scribble_armed = false;
  int mark_count = 0;
  const char *mark_intent = "";
  bool voice_available = false;
  bool voice_listening = false;
  bool voice_capturing = false;
  const char *voice_status = "";
  bool model_available = false;
  /* The model chip: WHO answers (the badge: "Mixie", "Claude API", "Local")
   * and WHICH model (the name), both as drawn (wm.mixar_agent_source_label /
   * wm.mixar_agent_chip_name, core/picker.py). */
  const char *chip_badge = "";
  const char *chip_name = "";
  /** Fixed chip words and the voice status are measured as drawn: the island
   *  passes its UI translation; null (the harness) measures the English.
   *  The model label and the reading's intent arrive already as drawn. */
  const char *(*translate)(const char *msgid) = nullptr;
};

/** Chip metrics in device pixels (theme artboard units times the island unit). */
struct AgentChipMetrics {
  float icon;      /* Glyph box. */
  float icon_gap;  /* Icon to label, and the padding unit (3x). */
  float pad_x;     /* Chip side padding. */
  float switch_w;  /* Auto's ON/OFF track. */
  float clear_w;   /* The clear-marks X chip. */
  float wave_w;    /* Voice's live ECG trace. */
  float text_size; /* Chip label font size, for the reading floor. */
  float unit = 1.0f; /* Island artboard unit in device pixels (the provider tokens). */
};

/* -------------------------------------------------------------------- */
/** \name The model chip
 *
 * One chip, right of Auto, that always names who answers and which model:
 * a small badge pill with the source word ("Mixie", "Claude API", "Codex",
 * "Local"), the model name, and the filled chevron (it opens the model
 * card, agent_ui_model_card.hh). Four forms for the width ladder: Full
 * (badge + name + chevron), Full with the name elided to
 * #AGENT_CHIP_NAME_FLOOR (a long name keeps both words before it loses the
 * badge; a short one measures as Full), Label (name + chevron), Icon (the
 * badge alone — "who" outlives "which" when space is gone). The painter
 * elides the name into whatever width the chip was given. Tokens are island
 * units (2.1256 per frame px of the designer's chip row).
 * \{ */

inline constexpr float AGENT_PROVIDER_RADIUS = 17.6f;       /* 8.28 px, every rounded shape */
inline constexpr float AGENT_PROVIDER_CHEVRON_W = 13.6f;    /* 6.4 px filled triangle */
inline constexpr float AGENT_PROVIDER_CHEVRON_H = 11.7f;    /* 5.5 px */
inline constexpr float AGENT_CHIP_BADGE_INSET = 4.25f;      /* 2 px, badge pill inside the chip */
inline constexpr float AGENT_CHIP_BADGE_PAD = 13.5f;        /* 6.35 px, badge word inset */
inline constexpr float AGENT_CHIP_NAME_GAP = 13.8f;         /* 6.5 px, badge -> name */
inline constexpr float AGENT_CHIP_NAME_PAD = 13.6f;         /* 6.4 px, name inset without a badge */
inline constexpr float AGENT_CHIP_CHEVRON_GAP = 20.0f;      /* 9.5 px, name -> chevron */
inline constexpr float AGENT_CHIP_CHEVRON_PAD = 11.5f;      /* 5.4 px, chevron -> chip edge */
/** The badge word is set a size down from the chip font. */
inline constexpr float AGENT_CHIP_BADGE_TEXT = 0.86f;
/** The elided rung keeps this much name, in chip font sizes (~7 glyphs). */
inline constexpr float AGENT_CHIP_NAME_FLOOR = 4.0f;
/** Weights (Manrope's variable axis): the name and the badge are semibold. */
inline constexpr int AGENT_PROVIDER_WEIGHT_STRONG = 600;
inline constexpr int AGENT_PROVIDER_WEIGHT_REGULAR = 400;

/** One measured chip, device pixels. */
struct AgentProviderSizes {
  float badge_w = 0.0f; /* The badge pill (word + its padding). */
  float name_w = 0.0f;  /* The model name. */
  float full_w = 0.0f;  /* Badge + name + chevron. */
  float elided_w = 0.0f; /* Full with the name elided to its floor (<= full_w). */
  float label_w = 0.0f; /* Name + chevron. */
  float icon_w = 0.0f;  /* The badge alone. */
};

/** Measure the chip's forms. \a strong_width (label, size ratio) measures
 *  at #AGENT_PROVIDER_WEIGHT_STRONG and the chip font times the ratio: the
 *  badge at #AGENT_CHIP_BADGE_TEXT, as drawn, and the name at 1; \a text_width
 *  is kept for callers measuring regular text. */
template<typename TextWidthFn, typename StrongWidthFn>
inline AgentProviderSizes agent_provider_sizes(const AgentChipRowInputs &in,
                                               const AgentChipMetrics &m,
                                               const TextWidthFn & /*text_width*/,
                                               const StrongWidthFn &strong_width)
{
  const float u = m.unit;
  AgentProviderSizes r;
  const float chevron = AGENT_CHIP_CHEVRON_GAP * u + AGENT_PROVIDER_CHEVRON_W * u +
                        AGENT_CHIP_CHEVRON_PAD * u;
  const float inset = AGENT_CHIP_BADGE_INSET * u;
  r.badge_w = AGENT_CHIP_BADGE_PAD * u + strong_width(in.chip_badge, AGENT_CHIP_BADGE_TEXT) +
              AGENT_CHIP_BADGE_PAD * u;
  r.name_w = strong_width(in.chip_name, 1.0f);
  r.full_w = inset + r.badge_w + AGENT_CHIP_NAME_GAP * u + r.name_w + chevron;
  r.elided_w = r.full_w - r.name_w + std::min(r.name_w, AGENT_CHIP_NAME_FLOOR * m.text_size);
  r.label_w = AGENT_CHIP_NAME_PAD * u + r.name_w + chevron;
  r.icon_w = inset + r.badge_w + inset;
  return r;
}

/** \} */

/**
 * Measure every form of every shown chip with \a text_width (label -> px).
 * Voice keeps ONE width for idle and capturing, so Stop and its trace never
 * shift Auto or the model chip; permission/finishing keep their status word.
 */
template<typename TextWidthFn, typename StrongWidthFn>
inline void agent_chip_forms(const AgentChipRowInputs &in,
                             const AgentChipMetrics &m,
                             const TextWidthFn &text_width,
                             const StrongWidthFn &strong_width,
                             AgentChipForms (&r_chips)[AGENT_CHIP_SLOT_COUNT])
{
  const float padding = 3.0f * m.icon_gap;
  auto as_drawn = [&](const char *label, const float icon) {
    return text_width(label) + icon + padding + 2.0f;
  };
  auto width = [&](const char *label, const float icon) {
    return as_drawn(in.translate ? in.translate(label) : label, icon);
  };
  /* Every chip's floor, and Upload Reference's hard one: its mark alone. */
  const float icon_only = m.icon + padding;
  for (AgentChipForms &chip : r_chips) {
    chip = {};
  }
  r_chips[AGENT_CHIP_SLOT_UPLOAD] = {
      {width("Attach", m.icon), width("Attach", m.icon), icon_only}, 3};
  if (in.scribble_available) {
    const char *annotation = in.scribble_armed ? "Done" : "Sketch";
    r_chips[AGENT_CHIP_SLOT_SCRIBBLE] = {{width(annotation, m.icon), icon_only}, 2};
  }
  if (in.voice_available) {
    const float idle = width("Voice", m.icon);
    const float stop = width("Stop", m.icon);
    const float capture = stop + m.wave_w + m.icon_gap;
    if (in.voice_capturing) {
      r_chips[AGENT_CHIP_SLOT_VOICE] = {{std::max(idle, capture), stop, icon_only}, 3};
    }
    else if (in.voice_listening) {
      r_chips[AGENT_CHIP_SLOT_VOICE] = {{width(in.voice_status, m.icon), icon_only}, 2};
    }
    else {
      r_chips[AGENT_CHIP_SLOT_VOICE] = {{std::max(idle, capture), icon_only}, 2};
    }
  }
  r_chips[AGENT_CHIP_SLOT_AUTO] = {{width("Auto", m.switch_w) + m.pad_x, m.switch_w + 2.0f * m.pad_x},
                                   2};
  if (in.model_available) {
    /* The model chip: badge + name, the same elided, the name alone, the badge
     * alone. Its painter maps the forms (agent_ui_layout_fit_controls). */
    const AgentProviderSizes p = agent_provider_sizes(in, m, text_width, strong_width);
    r_chips[AGENT_CHIP_SLOT_MODEL] = {
        {p.full_w, p.elided_w, p.label_w, std::max(p.icon_w, icon_only)}, 4};
  }
  if (in.scribble_armed || in.mark_count) {
    /* The reading label elides down to about two glyphs beside its chevron. */
    const float reading = in.mark_intent[0] ? as_drawn(in.mark_intent, m.icon) :
                                              width("Auto detect", m.icon);
    const float floor = m.icon * 0.7f + m.icon_gap + 2.0f * m.pad_x + m.text_size * 1.5f;
    r_chips[AGENT_CHIP_SLOT_READING] = {{reading, std::min(reading, floor)}, 2};
  }
  if (in.mark_count && !in.scribble_armed) {
    r_chips[AGENT_CHIP_SLOT_CLEAR] = {{m.clear_w}, 1};
  }
}

/** One measurer for every weight (the harness: a fixed advance per glyph,
 *  so a size ratio scales it exactly). */
template<typename TextWidthFn>
inline void agent_chip_forms(const AgentChipRowInputs &in,
                             const AgentChipMetrics &m,
                             const TextWidthFn &text_width,
                             AgentChipForms (&r_chips)[AGENT_CHIP_SLOT_COUNT])
{
  const auto strong_width = [&](const char *label, const float ratio) {
    return text_width(label) * ratio;
  };
  agent_chip_forms(in, m, text_width, strong_width, r_chips);
}

inline constexpr AgentChipSlot AGENT_CHIP_SHED_ORDER[] = {
    AGENT_CHIP_SLOT_VOICE,
    AGENT_CHIP_SLOT_AUTO,
    AGENT_CHIP_SLOT_SCRIBBLE,
    AGENT_CHIP_SLOT_READING,
    AGENT_CHIP_SLOT_VOICE,
};

/** Place the chips of \a chips inside \a span, each followed by \a gap (the
 *  last gap separates the row from Send). */
inline AgentChipFit agent_chip_fit(const AgentChipForms (&chips)[AGENT_CHIP_SLOT_COUNT],
                                   const float span,
                                   const float gap)
{
  AgentChipFit fit;
  const AgentChipForms &upload = chips[AGENT_CHIP_SLOT_UPLOAD];
  const float upload_full = upload.width[0];
  const float upload_reference = upload.count > 1 ? upload.width[1] : upload_full;
  const float upload_floor = upload.width[std::max(0, upload.count - 1)];

  /* Everything but Upload and the model chip: the controls that must stay. */
  auto core = [&]() {
    float used = 0.0f;
    for (int slot = 0; slot < AGENT_CHIP_SLOT_COUNT; slot++) {
      if (slot == AGENT_CHIP_SLOT_UPLOAD || slot == AGENT_CHIP_SLOT_MODEL ||
          chips[slot].count == 0)
      {
        continue;
      }
      used += chips[slot].width[fit.form[slot]] + gap;
    }
    return used;
  };

  bool shed = false;
  for (const AgentChipSlot slot : AGENT_CHIP_SHED_ORDER) {
    if (span - core() - gap >= upload_floor) {
      break;
    }
    if (fit.form[slot] + 1 < chips[slot].count) {
      fit.form[slot]++;
      shed = true;
    }
  }
  const float rest_fixed = core();

  /* Model: walk its ladder while "Reference" survives the purchase; then its
   * icon alone may push Upload toward the icon floor; past that it drops. It
   * is never bought once a core chip had to shed a word (a lone star must not
   * cost "Auto" its label), and narrowing the window only ever takes from it —
   * a second pass that retried the full label regrew it as the row shrank. */
  const AgentChipForms &model = chips[AGENT_CHIP_SLOT_MODEL];
  float model_w = 0.0f;
  fit.form[AGENT_CHIP_SLOT_MODEL] = model.count;
  auto affordable = [&](const float w, const float upload_min) {
    return span - (rest_fixed + w + gap) - gap >= upload_min;
  };
  if (!shed) {
    for (int i = 0; i < model.count; i++) {
      if (affordable(model.width[i], upload_reference)) {
        model_w = model.width[i];
        fit.form[AGENT_CHIP_SLOT_MODEL] = i;
        break;
      }
    }
    const int icon = model.count - 1;
    if (model_w <= 0.0f && icon >= 0 && affordable(model.width[icon], upload_floor)) {
      model_w = model.width[icon];
      fit.form[AGENT_CHIP_SLOT_MODEL] = icon;
    }
  }

  const float rest = rest_fixed + (model_w > 0.0f ? model_w + gap : 0.0f);
  const float budget = span - rest - gap;
  fit.compact_reference = upload_full > budget;
  const float upload_w = std::max(upload_floor,
                                  std::min(fit.compact_reference ? upload_reference : upload_full,
                                           budget));
  fit.form[AGENT_CHIP_SLOT_UPLOAD] = upload_w >= upload_full ? 0 :
                                     upload_w >= upload_reference ? 1 : 2;

  for (int slot = 0; slot < AGENT_CHIP_SLOT_COUNT; slot++) {
    if (chips[slot].count == 0) {
      continue;
    }
    fit.width[slot] = slot == AGENT_CHIP_SLOT_UPLOAD ? upload_w :
                      slot == AGENT_CHIP_SLOT_MODEL  ? model_w :
                                                       chips[slot].width[fit.form[slot]];
  }
  fit.fits = rest + upload_w + gap <= span + 0.5f;
  return fit;
}

}  // namespace blender
