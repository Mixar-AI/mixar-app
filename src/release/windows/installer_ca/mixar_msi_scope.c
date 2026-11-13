/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * The installer's scope decision (#2079), with no Windows dependency.
 *
 * The rule the product owner set: every existing user moves out of Program
 * Files in this version with at most the one administrator prompt they get
 * today, and nobody is left worse off than today. So the move happens only
 * when this account's own Mixar is in Program Files, the install runs
 * elevated as the signed-in user, nothing allows apps by folder, Windows
 * Installer lets the user install without an administrator afterwards, and
 * no other account uses that copy; any other elevated install updates Program
 * Files where it is, exactly as every earlier release did. A refusal is
 * left only where today's behaviour would fail or leave a second copy, and
 * none of them can loop: each says what to do instead.
 */

#include "mixar_msi_scope.h"

int mixar_scope_decide(const MixarScopeFacts *f, const char **r_reason)
{
  const char *unused;
  const char **reason = r_reason ? r_reason : &unused;
  *reason = "";

  if (f->all_users) {
    /* A machine install keeps an existing install's folder (an IT one may be
     * anywhere) unless the command line names another. */
    if (f->own_product && f->own_location_known && !f->root_from_command_line) {
      *reason = "machine_scope";
      return MIXAR_SCOPE_KEEP;
    }
    return MIXAR_SCOPE_FRESH;
  }

  /* Per-user scope from here on. */
  if (!f->own_product) {
    if (f->system_account) {
      /* A deployment tool without ALLUSERS=1 would install into SYSTEM's own
       * profile, where no user ever sees it. */
      *reason = "system_account";
      return MIXAR_SCOPE_REFUSE_SYSTEM;
    }
    if (f->machine_product) {
      /* Windows Installer finds related products only in the package's own
       * context: this would be a second copy beside the machine's. */
      *reason = "machine_product";
      return MIXAR_SCOPE_REFUSE_MACHINE;
    }
    if (f->program_files_exe) {
      if (f->privileged) {
        /* Another account's Program Files copy, an administrator approving
         * someone else's update (a standard user's, or Windows 11
         * Administrator Protection's separate account): as today. */
        *reason = "other_account";
        return MIXAR_SCOPE_IN_PLACE_PROGRAM_FILES;
      }
      *reason = "not_elevated";
      return MIXAR_SCOPE_BESIDE;
    }
    return MIXAR_SCOPE_FRESH;
  }

  /* Only a release before #2079 can have no readable folder, and each was
   * installed elevated, in Program Files or a folder IT chose: as far as
   * this install can tell, it is a Program Files copy. */
  const int in_program_files = f->own_in_program_files || !f->own_location_known;
  if (in_program_files && !f->privileged) {
    /* Removing a Program Files install needs an administrator: without one
     * the upgrade would fail at its very end and roll back. */
    if (f->full_ui && !f->elevated_child) {
      *reason = "not_elevated";
      return MIXAR_SCOPE_RELAUNCH;
    }
    *reason = "not_elevated";
    return MIXAR_SCOPE_REFUSE_NEEDS_ADMIN;
  }
  if (f->root_from_command_line) {
    *reason = "command_line";
    return MIXAR_SCOPE_FRESH;
  }
  if (!f->own_location_known) {
    /* Where that release put it (MixarInspect), never moved unchecked. */
    *reason = "location_unknown";
    return MIXAR_SCOPE_IN_PLACE;
  }
  if (!f->own_in_program_files) {
    /* Already in the profile, or a folder the user chose: it stays. */
    *reason = "own_folder";
    return MIXAR_SCOPE_KEEP;
  }
  if (f->system_account) {
    *reason = "system_account";
    return MIXAR_SCOPE_IN_PLACE;
  }
  if (!f->session_matches) {
    /* Approved with another account's credentials: the copy would land in
     * that account's profile, and the signed-in user would lose theirs. */
    *reason = "other_session_user";
    return MIXAR_SCOPE_IN_PLACE;
  }
  if (f->path_policy) {
    /* Rules that allow programs by folder would block the moved copy. */
    *reason = "path_policy";
    return MIXAR_SCOPE_IN_PLACE;
  }
  if (f->installer_policy) {
    /* Windows Installer allows installs only with an administrator (DisableMSI
     * 1 or 2, or Windows Server's default): moved, every update would still
     * need the prompt, so the move would gain nothing. */
    *reason = "installer_policy";
    return MIXAR_SCOPE_IN_PLACE;
  }
  if (f->program_files_shared) {
    *reason = "shared";
    return MIXAR_SCOPE_IN_PLACE;
  }
  if (f->program_files_in_use) {
    /* The move uninstalls the old copy: a file another process holds there
     * makes that uninstall stop at a "reboot required" prompt. In place the
     * held file is replaced at the next restart, with no prompt. */
    *reason = "files_in_use";
    return MIXAR_SCOPE_IN_PLACE;
  }
  *reason = "own_program_files";
  return MIXAR_SCOPE_MOVE;
}

const char *mixar_scope_action_name(int action)
{
  switch (action) {
    case MIXAR_SCOPE_FRESH:
      return "fresh";
    case MIXAR_SCOPE_KEEP:
      return "keep";
    case MIXAR_SCOPE_MOVE:
      return "move";
    case MIXAR_SCOPE_IN_PLACE:
      return "in_place";
    case MIXAR_SCOPE_IN_PLACE_PROGRAM_FILES:
      return "in_place_program_files";
    case MIXAR_SCOPE_BESIDE:
      return "beside";
    case MIXAR_SCOPE_RELAUNCH:
      return "relaunch";
    case MIXAR_SCOPE_REFUSE_SYSTEM:
    case MIXAR_SCOPE_REFUSE_MACHINE:
    case MIXAR_SCOPE_REFUSE_NEEDS_ADMIN:
      return "refuse";
  }
  return "";
}

const char *mixar_scope_refusal(int action)
{
  switch (action) {
    case MIXAR_SCOPE_REFUSE_SYSTEM:
      return "system";
    case MIXAR_SCOPE_REFUSE_MACHINE:
      return "machine";
    case MIXAR_SCOPE_REFUSE_NEEDS_ADMIN:
      return "needs_admin";
  }
  return "";
}

/* ------------------------------------------------------------------------ */

static wchar_t fold(wchar_t c)
{
  if (c == L'/') {
    return L'\\';
  }
  return (c >= L'a' && c <= L'z') ? (wchar_t)(c - L'a' + L'A') : c;
}

/* Length without trailing separators. */
static size_t trimmed_length(const wchar_t *s)
{
  size_t n = wcslen(s);
  while (n > 0 && (s[n - 1] == L'\\' || s[n - 1] == L'/')) {
    n--;
  }
  return n;
}

int mixar_path_within(const wchar_t *path, const wchar_t *root)
{
  if (!path || !root) {
    return 0;
  }
  const size_t root_len = trimmed_length(root);
  const size_t path_len = trimmed_length(path);
  if (root_len == 0 || path_len < root_len) {
    return 0;
  }
  for (size_t i = 0; i < root_len; i++) {
    if (fold(path[i]) != fold(root[i])) {
      return 0;
    }
  }
  return path_len == root_len || fold(path[root_len]) == L'\\';
}

int mixar_path_equal(const wchar_t *a, const wchar_t *b)
{
  if (!a || !b || trimmed_length(a) == 0) {
    return 0;
  }
  return trimmed_length(a) == trimmed_length(b) && mixar_path_within(a, b);
}

/* Do the first `n` characters of `a` and `b` match, ignoring ASCII case? */
static int same_start(const wchar_t *a, const wchar_t *b, size_t n)
{
  for (size_t i = 0; i < n; i++) {
    if (!a[i] || fold(a[i]) != fold(b[i])) {
      return 0;
    }
  }
  return 1;
}

int mixar_profile_of_another_person(const wchar_t *profile_sid, const wchar_t *user_sid)
{
  static const wchar_t *const people[] = {L"S-1-5-21-", L"S-1-12-1-"};
  size_t n = profile_sid ? wcslen(profile_sid) : 0;
  int person = 0;
  for (int i = 0; i < 2; i++) {
    const size_t prefix = wcslen(people[i]);
    person = person || (n > prefix && same_start(profile_sid, people[i], prefix));
  }
  if (!person) {
    return 0;
  }
  if (n > 4 && same_start(profile_sid + n - 4, L".bak", 4)) {
    n -= 4;
  }
  return !user_sid || wcslen(user_sid) != n || !same_start(profile_sid, user_sid, n);
}

int mixar_profile_folder_maybe_there(unsigned int attributes, unsigned int error)
{
  /* INVALID_FILE_ATTRIBUTES; ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND. */
  return attributes != 0xFFFFFFFFu || (error != 2 && error != 3);
}

static int is_hex(wchar_t c)
{
  return (c >= L'0' && c <= L'9') || (c >= L'a' && c <= L'f') || (c >= L'A' && c <= L'F');
}

int mixar_pack_guid(const wchar_t *guid, wchar_t *out)
{
  wchar_t hex[32];
  int n = 0;
  if (!guid || wcslen(guid) != 38 || guid[0] != L'{' || guid[37] != L'}') {
    return 0;
  }
  for (int i = 1; i < 37; i++) {
    const int dash = (i == 9 || i == 14 || i == 19 || i == 24);
    if (dash != (guid[i] == L'-')) {
      return 0;
    }
    if (!dash) {
      if (!is_hex(guid[i])) {
        return 0;
      }
      hex[n++] = fold(guid[i]);
    }
  }
  /* Groups 1-3 reversed; every byte of the last 8 has its digits swapped. */
  for (int i = 0; i < 8; i++) {
    out[i] = hex[7 - i];
  }
  for (int i = 0; i < 4; i++) {
    out[8 + i] = hex[11 - i];
    out[12 + i] = hex[15 - i];
  }
  for (int i = 16; i < 32; i += 2) {
    out[i] = hex[i + 1];
    out[i + 1] = hex[i];
  }
  out[32] = L'\0';
  return 1;
}
