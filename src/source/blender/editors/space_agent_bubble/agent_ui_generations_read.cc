/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * The My Generations pane's readers: the guarded RNA getters every source
 * shares, and the time arithmetic behind a tile's "4d ago".
 *
 * Split out of the gathering pass only to keep both files inside the 500-line
 * rule; there is no second concept here.
 */

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <string>

#include "MEM_guardedalloc.h"

#include "BLI_fileops.h"
#include "BLI_map.hh"
#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "RNA_access.hh"

#include "agent_ui_generations_intern.hh"

namespace {

/** Days since the civil epoch — portable, unlike `timegm`, which is not on
 * Windows. Howard Hinnant's algorithm, valid for the Gregorian calendar. */
long long days_from_civil(int y, const unsigned m, const unsigned d)
{
  y -= int(m <= 2);
  const long long era = (y >= 0 ? y : y - 399) / 400;
  const unsigned yoe = unsigned(y - era * 400);
  const unsigned doy = (153u * (m + (m > 2 ? -3u : 9u)) + 2u) / 5u + d - 1u;
  const unsigned doe = yoe * 365u + yoe / 4u - yoe / 100u + doy;
  return era * 146097LL + static_cast<long long>(doe) - 719468LL;
}

}  // namespace

/* -------------------------------------------------------------------- */
/** \name RNA reads (never the bare string getter — it is strcpy-shaped)
 * \{ */

void gen_read_string(PointerRNA *ptr, const char *name, char *out, const int out_maxncpy)
{
  out[0] = '\0';
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  if (!prop || RNA_property_type(prop) != PROP_STRING) {
    return;
  }
  char fixed[512];
  int len = 0;
  char *value = RNA_property_string_get_alloc(ptr, prop, fixed, sizeof(fixed), &len);
  if (value) {
    BLI_strncpy(out, value, out_maxncpy);
    if (value != fixed) {
      MEM_freeN(value);
    }
  }
}

float gen_read_float(PointerRNA *ptr, const char *name)
{
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  return (prop && RNA_property_type(prop) == PROP_FLOAT) ? RNA_property_float_get(ptr, prop) :
                                                           0.0f;
}

/** The enum's stable identifier, never its index — an index repoints. */
void gen_read_enum_id(PointerRNA *ptr, const char *name, char *out, const int out_maxncpy)
{
  out[0] = '\0';
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  if (!prop || RNA_property_type(prop) != PROP_ENUM) {
    return;
  }
  const char *ident = nullptr;
  if (RNA_property_enum_identifier(
          nullptr, ptr, prop, RNA_property_enum_get(ptr, prop), &ident) &&
      ident)
  {
    BLI_strncpy(out, ident, out_maxncpy);
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Time
 * \{ */

/** Unix seconds for an ISO-8601 stamp, or 0 when it does not parse. The
 * moodboard writes UTC (`datetime.now(timezone.utc).isoformat()`), so the
 * offset suffix is ignored rather than applied. */
double gen_epoch_from_iso(const char *iso)
{
  if (!iso || !iso[0]) {
    return 0.0;
  }
  int y = 0, mo = 0, d = 0, h = 0, mi = 0, s = 0;
  if (sscanf(iso, "%4d-%2d-%2dT%2d:%2d:%2d", &y, &mo, &d, &h, &mi, &s) < 3) {
    return 0.0;
  }
  if (y < 1970 || mo < 1 || mo > 12 || d < 1 || d > 31) {
    return 0.0;
  }
  return double(days_from_civil(y, unsigned(mo), unsigned(d))) * 86400.0 + h * 3600.0 +
         mi * 60.0 + s;
}

/** "4d ago" — the design's caption. Coarse on purpose: a browser's age line
 * answers "which one is the recent one", not "when exactly". */
void gen_format_age(const double epoch, char r_out[32])
{
  r_out[0] = '\0';
  if (epoch <= 0.0) {
    return;
  }
  const double delta = double(time(nullptr)) - epoch;
  if (delta < 60.0) {
    BLI_strncpy(r_out, "just now", 32);
  }
  else if (delta < 3600.0) {
    BLI_snprintf(r_out, 32, "%dm ago", int(delta / 60.0));
  }
  else if (delta < 86400.0) {
    BLI_snprintf(r_out, 32, "%dh ago", int(delta / 3600.0));
  }
  else if (delta < 86400.0 * 7.0) {
    BLI_snprintf(r_out, 32, "%dd ago", int(delta / 86400.0));
  }
  else {
    BLI_snprintf(r_out, 32, "%dw ago", int(delta / (86400.0 * 7.0)));
  }
}

/** Modification time of an asset's .blend, memoised.
 *
 * An archived generation's file never changes, so one stat per path per
 * session is enough — and it has to be memoised, because the island repaints
 * on every mouse move and a library of a few hundred assets would otherwise
 * be a few hundred syscalls a frame. */
double gen_blend_mtime(const char *path)
{
  static blender::Map<std::string, double> cache;
  if (!path || !path[0]) {
    return 0.0;
  }
  const std::string key(path);
  if (const double *hit = cache.lookup_ptr(key)) {
    return *hit;
  }
  /* Bounded: a pathological library must not grow this without limit. */
  if (cache.size() > 4096) {
    cache.clear();
  }
  BLI_stat_t st;
  const double mtime = (BLI_stat(path, &st) == 0) ? double(st.st_mtime) : 0.0;
  cache.add_new(key, mtime);
  return mtime;
}

/** \} */
