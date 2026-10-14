/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup wm
 *
 * Main-thread stall monitor: per-iteration phase timing, breadcrumb scopes
 * and the JSONL sink. See `WM_stall_monitor.hh` for the contract.
 */

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <atomic>
#include <ctime>
#include <optional>
#include <string>
#include <utility>

#include "BLI_fileops.h"
#include "BLI_path_utils.hh"
#include "BLI_string.h"
#include "BLI_threads.h"
#include "BLI_time.h"

#include "BKE_appdir.hh"
#include "BKE_context.hh"
#include "BKE_global.hh"

#include "WM_api.hh"
#include "WM_stall_monitor.hh"

namespace blender {

namespace {

constexpr int SCOPE_NAME_LEN = 96;
constexpr int SCOPE_STACK_MAX = 16;
constexpr int TOP_MAX = 4;
constexpr int KIND_MAX = 12;
constexpr size_t LOG_ROTATE_BYTES = 4 * 1024 * 1024;
constexpr double DEFAULT_THRESHOLD_MS = 100.0;

struct Scope {
  const char *kind;
  char name[SCOPE_NAME_LEN];
  double start;
  int depth;
};

struct Top {
  const char *kind;
  char name[SCOPE_NAME_LEN];
  double ms;
  int depth;
};

struct KindCount {
  const char *kind;
  int count;
};

struct Monitor {
  bool configured = false;
  bool enabled = true;
  bool print = false;
  double threshold_ms = DEFAULT_THRESHOLD_MS;
  std::string log_path;
  size_t bytes_written = 0;
  double start_time = 0.0;
  int records = 0;

  /* Per iteration. */
  double iter_start = 0.0;
  double phase_start = 0.0;
  double phase_ms[MIXAR_STALL_PHASE_NUM] = {};
  Scope stack[SCOPE_STACK_MAX];
  int depth = 0;
  Top top[TOP_MAX];
  int top_num = 0;
  KindCount kinds[KIND_MAX];
  int kinds_num = 0;
  int scopes_total = 0;
};

Monitor g_mon;
std::atomic<uint64_t> g_iteration{0};

void configure()
{
  g_mon.configured = true;
  g_mon.start_time = BLI_time_now_seconds();

  if (const char *env = BLI_getenv("MIXAR_STALL_THRESHOLD_MS")) {
    const double value = atof(env);
    if (value > 0.0) {
      g_mon.threshold_ms = value;
    }
  }
  if (const char *env = BLI_getenv("MIXAR_STALL_PRINT")) {
    g_mon.print = (env[0] != '\0' && env[0] != '0');
  }
  if (const char *env = BLI_getenv("MIXAR_STALL_LOG")) {
    if (STREQ(env, "off") || STREQ(env, "0")) {
      g_mon.enabled = false;
    }
    else if (env[0] != '\0') {
      g_mon.log_path = env;
    }
  }
  if (g_mon.enabled && g_mon.log_path.empty()) {
    if (const std::optional<std::string> dir = BKE_appdir_folder_id_create(BLENDER_USER_CONFIG,
                                                                           "mixar"))
    {
      char path[FILE_MAX];
      BLI_path_join(path, sizeof(path), dir->c_str(), "stalls.jsonl");
      g_mon.log_path = path;
    }
    else {
      g_mon.enabled = false;
    }
  }
  if (g_mon.enabled) {
    g_mon.bytes_written = BLI_file_size(g_mon.log_path.c_str());
    if (g_mon.bytes_written == size_t(-1)) {
      g_mon.bytes_written = 0;
    }
  }
}

void rotate_if_needed()
{
  if (g_mon.bytes_written < LOG_ROTATE_BYTES) {
    return;
  }
  const std::string old = g_mon.log_path + ".1";
  BLI_rename_overwrite(g_mon.log_path.c_str(), old.c_str());
  g_mon.bytes_written = 0;
}

void json_escape(const char *src, char *dst, size_t dst_len)
{
  size_t j = 0;
  for (size_t i = 0; src[i] != '\0' && j + 2 < dst_len; i++) {
    const unsigned char c = (unsigned char)src[i];
    if (c == '"' || c == '\\') {
      dst[j++] = '\\';
      dst[j++] = char(c);
    }
    else if (c < 0x20) {
      dst[j++] = ' ';
    }
    else {
      dst[j++] = char(c);
    }
  }
  dst[j] = '\0';
}

void count_kind(const char *kind)
{
  for (int i = 0; i < g_mon.kinds_num; i++) {
    if (g_mon.kinds[i].kind == kind || STREQ(g_mon.kinds[i].kind, kind)) {
      g_mon.kinds[i].count++;
      return;
    }
  }
  if (g_mon.kinds_num < KIND_MAX) {
    g_mon.kinds[g_mon.kinds_num++] = {kind, 1};
  }
}

void record_top(const Scope &scope, double ms)
{
  if (ms < 1.0) {
    /* A crumb that explains nothing only hides that nothing explained the stall. */
    return;
  }
  int slot = g_mon.top_num;
  if (slot == TOP_MAX) {
    int weakest = 0;
    for (int i = 1; i < TOP_MAX; i++) {
      if (g_mon.top[i].ms < g_mon.top[weakest].ms) {
        weakest = i;
      }
    }
    if (ms <= g_mon.top[weakest].ms) {
      return;
    }
    slot = weakest;
  }
  else {
    g_mon.top_num++;
  }
  Top &top = g_mon.top[slot];
  top.kind = scope.kind;
  STRNCPY(top.name, scope.name);
  top.ms = ms;
  top.depth = scope.depth;
}

void write_record(const bContext *C, double total_ms)
{
  g_mon.records++;

  char line[2048];
  size_t len = 0;

  char stamp[32];
  const time_t now = time(nullptr);
  tm utc;
#ifdef _WIN32
  gmtime_s(&utc, &now);
#else
  gmtime_r(&now, &utc);
#endif
  strftime(stamp, sizeof(stamp), "%Y-%m-%dT%H:%M:%SZ", &utc);

  const wmWindowManager *wm = C ? CTX_wm_manager(C) : nullptr;
  const bool job_running = wm ? WM_jobs_has_running(wm) : false;

  len += BLI_snprintf_rlen(line + len,
                           sizeof(line) - len,
                           "{\"t\":\"%s\",\"up\":%.1f,\"seq\":%d,\"it\":%llu,\"ms\":%.0f,\"ph\":[%.0f,%.0f,%.0f,%.0f],"
                           "\"job\":%d,\"scopes\":%d,\"top\":[",
                           stamp,
                           BLI_time_now_seconds() - g_mon.start_time,
                           g_mon.records,
                           (unsigned long long)g_iteration.load(std::memory_order_relaxed),
                           total_ms,
                           g_mon.phase_ms[0],
                           g_mon.phase_ms[1],
                           g_mon.phase_ms[2],
                           g_mon.phase_ms[3],
                           int(job_running),
                           g_mon.scopes_total);

  /* Longest first. */
  for (int i = 1; i < g_mon.top_num; i++) {
    for (int j = i; j > 0 && g_mon.top[j].ms > g_mon.top[j - 1].ms; j--) {
      std::swap(g_mon.top[j], g_mon.top[j - 1]);
    }
  }
  for (int i = 0; i < g_mon.top_num && len < sizeof(line); i++) {
    char name[SCOPE_NAME_LEN * 2];
    json_escape(g_mon.top[i].name, name, sizeof(name));
    len += BLI_snprintf_rlen(line + len,
                             sizeof(line) - len,
                             "%s{\"k\":\"%s\",\"n\":\"%s\",\"ms\":%.0f,\"d\":%d}",
                             i ? "," : "",
                             g_mon.top[i].kind,
                             name,
                             g_mon.top[i].ms,
                             g_mon.top[i].depth);
  }
  len += BLI_snprintf_rlen(line + len, sizeof(line) - len, "],\"n\":{");
  for (int i = 0; i < g_mon.kinds_num && len < sizeof(line); i++) {
    len += BLI_snprintf_rlen(line + len,
                             sizeof(line) - len,
                             "%s\"%s\":%d",
                             i ? "," : "",
                             g_mon.kinds[i].kind,
                             g_mon.kinds[i].count);
  }
  len += BLI_snprintf_rlen(line + len, sizeof(line) - len, "}}\n");
  if (len >= sizeof(line)) {
    /* Truncated: keep the line parseable by dropping it entirely. */
    return;
  }

  if (g_mon.print || (G.debug & G_DEBUG_WM)) {
    fputs("Mixar stall: ", stdout);
    fputs(line, stdout);
    fflush(stdout);
  }
  if (!g_mon.enabled) {
    return;
  }
  rotate_if_needed();
  if (FILE *fp = BLI_fopen(g_mon.log_path.c_str(), "ab")) {
    fwrite(line, 1, len, fp);
    fclose(fp);
    g_mon.bytes_written += len;
  }
}

}  // namespace

void Mixar_stall_iteration_begin()
{
  if (!g_mon.configured) {
    configure();
  }
  g_iteration.fetch_add(1, std::memory_order_relaxed);
  const double now = BLI_time_now_seconds();
  g_mon.iter_start = now;
  g_mon.phase_start = now;
  for (double &ms : g_mon.phase_ms) {
    ms = 0.0;
  }
  g_mon.depth = 0;
  g_mon.top_num = 0;
  g_mon.kinds_num = 0;
  g_mon.scopes_total = 0;
}

void Mixar_stall_phase_end(Mixar_StallPhase phase)
{
  const double now = BLI_time_now_seconds();
  g_mon.phase_ms[phase] = (now - g_mon.phase_start) * 1000.0;
  g_mon.phase_start = now;
}

void Mixar_stall_iteration_end(const bContext *C)
{
  if (!g_mon.configured) {
    return;
  }
  const double total_ms = (BLI_time_now_seconds() - g_mon.iter_start) * 1000.0;
  if (total_ms >= g_mon.threshold_ms) {
    write_record(C, total_ms);
  }
}

int Mixar_stall_scope_push(const char *kind, const char *name)
{
  if (!g_mon.configured || !BLI_thread_is_main() || g_mon.depth >= SCOPE_STACK_MAX) {
    return -1;
  }
  const int index = g_mon.depth++;
  Scope &scope = g_mon.stack[index];
  scope.kind = kind;
  STRNCPY(scope.name, name ? name : "");
  scope.start = BLI_time_now_seconds();
  scope.depth = index;
  return index;
}

void Mixar_stall_scope_pop(int index)
{
  if (index < 0 || index >= g_mon.depth || !BLI_thread_is_main()) {
    return;
  }
  const Scope &scope = g_mon.stack[index];
  const double ms = (BLI_time_now_seconds() - scope.start) * 1000.0;
  g_mon.scopes_total++;
  count_kind(scope.kind);
  record_top(scope, ms);
  g_mon.depth = index;
}

int Mixar_stall_record_count()
{
  return g_mon.records;
}

uint64_t Mixar_stall_iteration_count()
{
  return g_iteration.load(std::memory_order_relaxed);
}

}  // namespace blender
