/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * The MSI's custom actions (#2079), scheduled by WIX.template and the dialog
 * in WixUI_Blender.wxs:
 *
 * - MixarInspect (immediate, both sequences, after AppSearch): reads where
 *   this account's earlier Mixar is and the facts mixar_scope_decide needs,
 *   then sets INSTALL_ROOT (kept or updated in place), MIXAR_OLD_LOCATION,
 *   MIXAR_SCOPE_ACTION / _REASON and, for a refusal, MIXAR_SCOPE_REFUSAL,
 *   which LaunchConditions turns into a message.
 * - MixarMarker (immediate, execute, before CostFinalize): MIXAR_MOVED_FROM,
 *   the old folder, whenever this install lands elsewhere; the component
 *   MixarMovedFrom writes it to HKCU for the app.
 * - MixarRelaunchElevated (the wizard's Next on MixarElevateDlg): runs this
 *   package again with the administrator prompt.
 * - MixarCleanMachineAssociations (deferred, as SYSTEM): the machine-wide
 *   .mixar association a release before #2079 registered for a copy, once
 *   that copy is gone: after a move removed the old product, and after this
 *   product's own removal (a copy updated in place keeps its release's
 *   association, which this package's per-user unregister leaves).
 *
 * Built with the static runtime: it runs before Mixar's own runtime exists.
 * Every action returns success; a failure is logged and leaves Mixar where
 * it is.
 */

#include "mixar_msi_ca.h"
#include "mixar_msi_scope.h"

#include <shellapi.h>
#include <shlobj.h>
#include <stdarg.h>
#include <stdio.h>

int mixar_ca_get(MSIHANDLE h, const wchar_t *name, wchar_t *buf, DWORD cap)
{
  DWORD n = cap;
  if (MsiGetPropertyW(h, name, buf, &n) != ERROR_SUCCESS) {
    buf[0] = L'\0';
  }
  return buf[0] != L'\0';
}

void mixar_ca_set(MSIHANDLE h, const wchar_t *name, const wchar_t *value)
{
  MsiSetPropertyW(h, name, value);
}

void mixar_ca_log(MSIHANDLE h, const wchar_t *format, ...)
{
  wchar_t text[2048];
  va_list args;
  va_start(args, format);
  _vsnwprintf_s(text, 2048, _TRUNCATE, format, args);
  va_end(args);
  MSIHANDLE rec = MsiCreateRecord(0);
  if (rec) {
    MsiRecordSetStringW(rec, 0, text);
    MsiProcessMessage(h, INSTALLMESSAGE_INFO, rec);
    MsiCloseHandle(rec);
  }
}

void mixar_ca_dir(wchar_t *path, size_t cap)
{
  const size_t n = wcslen(path);
  if (n > 0 && path[n - 1] != L'\\' && n + 1 < cap) {
    path[n] = L'\\';
    path[n + 1] = L'\0';
  }
}

int mixar_ca_hklm_value(
    const wchar_t *key, const wchar_t *name, DWORD flags, void *out, DWORD *size)
{
  HKEY hkey;
  LSTATUS status;
  if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, key, 0, KEY_QUERY_VALUE | KEY_WOW64_64KEY, &hkey) !=
      ERROR_SUCCESS)
  {
    return 0;
  }
  status = RegGetValueW(hkey, NULL, name, flags, NULL, out, size);
  RegCloseKey(hkey);
  return status == ERROR_SUCCESS;
}

int mixar_ca_hklm_string(const wchar_t *key, const wchar_t *name, wchar_t *out, DWORD cap)
{
  DWORD size = cap * sizeof(wchar_t);
  out[0] = L'\0';
  if (!mixar_ca_hklm_value(key, name, RRF_RT_REG_SZ, out, &size)) {
    out[0] = L'\0';
  }
  return out[0] != L'\0';
}

int mixar_ca_file_exists(const wchar_t *path)
{
  const DWORD attributes = GetFileAttributesW(path);
  return attributes != INVALID_FILE_ATTRIBUTES && !(attributes & FILE_ATTRIBUTE_DIRECTORY);
}

static int flag(MSIHANDLE h, const wchar_t *name)
{
  wchar_t value[16];
  return mixar_ca_get(h, name, value, 16) && wcscmp(value, L"0") != 0;
}

/* An administrator's unelevated (UAC-filtered) token. In the wizard's own
 * sequence Windows Installer sets Privileged for such an account because it
 * could elevate, although this install will not (box run 20261113-024449). */
static int limited_token(void)
{
  HANDLE token = NULL;
  TOKEN_ELEVATION_TYPE type = TokenElevationTypeDefault;
  DWORD size = 0;
  if (!OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, TRUE, &token) &&
      !OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token))
  {
    return 0;
  }
  if (!GetTokenInformation(token, TokenElevationType, &type, sizeof(type), &size)) {
    type = TokenElevationTypeDefault;
  }
  CloseHandle(token);
  return type == TokenElevationTypeLimited;
}

/* ------------------------------------------------------------------------ */

UINT __stdcall MixarInspect(MSIHANDLE h)
{
  wchar_t program_files[MIXAR_CA_PATH], program_files_mixar[MIXAR_CA_PATH];
  wchar_t user_sid[256], component[64], upgrade_code[64], ui_level[16];
  wchar_t root[MIXAR_CA_PATH], exe[MIXAR_CA_PATH];
  MixarOwnProduct own;
  MixarScopeFacts f = {0};
  const char *reason = "";

  mixar_ca_hklm_string(MIXAR_CA_CURRENT_VERSION_KEY, L"ProgramW6432Dir", program_files,
                       MIXAR_CA_PATH);
  mixar_ca_dir(program_files, MIXAR_CA_PATH);
  swprintf(program_files_mixar, MIXAR_CA_PATH, L"%sMixar\\", program_files);
  mixar_ca_get(h, L"UserSID", user_sid, 256);
  mixar_ca_get(h, L"UpgradeCode", upgrade_code, 64);
  mixar_ca_get(h, L"UILevel", ui_level, 16);
  mixar_facts_exe_component(h, component, 64);
  mixar_facts_own_product(h, component, program_files, &own);

  f.all_users = flag(h, L"ALLUSERS");
  const int limited = limited_token();
  f.privileged = flag(h, L"Privileged") && !limited;
  f.system_account = _wcsicmp(user_sid, L"S-1-5-18") == 0;
  f.full_ui = wcscmp(ui_level, L"5") == 0;
  f.elevated_child = flag(h, L"MIXAR_ELEVATED_CHILD");
  f.own_product = own.found;
  f.own_location_known = own.location[0] != L'\0';
  f.own_in_program_files = program_files[0] && mixar_path_within(own.location, program_files);
  f.root_from_command_line = mixar_ca_get(h, L"INSTALL_ROOT", root, MIXAR_CA_PATH);
  f.machine_product = mixar_facts_machine_product(upgrade_code);
  swprintf(exe, MIXAR_CA_PATH, L"%smixar.exe", program_files_mixar);
  f.program_files_exe = program_files[0] && mixar_ca_file_exists(exe);
  /* Read only where they can change the answer. */
  if (!f.all_users && own.found && f.own_in_program_files && f.privileged) {
    f.session_matches = mixar_facts_session_matches(h, user_sid);
    f.path_policy = mixar_facts_path_policy();
    f.installer_policy = mixar_facts_installer_policy(h);
    f.program_files_shared = mixar_facts_program_files_shared(
        h, component, user_sid, program_files_mixar);
    /* The slowest read (every file of the copy), so only when it would move. */
    if (f.session_matches && !f.path_policy && !f.installer_policy && !f.program_files_shared) {
      f.program_files_in_use = mixar_facts_files_in_use(own.location);
    }
  }

  const int action = mixar_scope_decide(&f, &reason);
  wchar_t action_name[32], reason_name[32];
  swprintf(action_name, 32, L"%hs", mixar_scope_action_name(action));
  swprintf(reason_name, 32, L"%hs", reason);
  mixar_ca_log(h,
               L"Mixar: all_users=%d privileged=%d limited=%d system=%d full_ui=%d elevated_child=%d "
               L"own=%d own_location=%s own_in_program_files=%d root_from_command_line=%d "
               L"machine_product=%d program_files_exe=%d session_matches=%d path_policy=%d "
               L"installer_policy=%d shared=%d in_use=%d -> %s (%s)",
               f.all_users, f.privileged, limited, f.system_account, f.full_ui, f.elevated_child,
               f.own_product, own.location, f.own_in_program_files, f.root_from_command_line,
               f.machine_product, f.program_files_exe, f.session_matches, f.path_policy,
               f.installer_policy, f.program_files_shared, f.program_files_in_use, action_name,
               reason_name);

  mixar_ca_set(h, L"MIXAR_PROGRAM_FILES", program_files);
  if (limited) {
    /* The wizard's folder check (WixUI_Blender.wxs) reads it. */
    mixar_ca_set(h, L"MIXAR_LIMITED_TOKEN", L"1");
  }
  mixar_ca_set(h, L"MIXAR_SCOPE_ACTION", action_name);
  mixar_ca_set(h, L"MIXAR_SCOPE_REASON", reason_name);
  if (mixar_scope_refusal(action)[0]) {
    wchar_t refusal[32];
    swprintf(refusal, 32, L"%hs", mixar_scope_refusal(action));
    mixar_ca_set(h, L"MIXAR_SCOPE_REFUSAL", refusal);
  }
  /* Kept or in place: its folder, else (location_unknown) where every
   * release before #2079 put it, the old product's Uninstall InstallLocation
   * or Program Files\Mixar. An empty INSTALL_ROOT would be the per-user
   * default: a move nothing checked. */
  wchar_t where[MIXAR_CA_PATH];
  if (own.location[0]) {
    wcscpy_s(where, MIXAR_CA_PATH, own.location);
  }
  else if (mixar_ca_get(h, L"MIXAR_ARP_LOCATION", where, MIXAR_CA_PATH)) {
    mixar_ca_dir(where, MIXAR_CA_PATH);
  }
  else {
    wcscpy_s(where, MIXAR_CA_PATH, program_files_mixar);
  }
  switch (action) {
    case MIXAR_SCOPE_KEEP:
    case MIXAR_SCOPE_IN_PLACE:
      mixar_ca_set(h, L"INSTALL_ROOT", where);
      mixar_ca_set(h, L"MIXAR_OLD_LOCATION", where);
      break;
    case MIXAR_SCOPE_IN_PLACE_PROGRAM_FILES:
      mixar_ca_set(h, L"INSTALL_ROOT", program_files_mixar);
      mixar_ca_set(h, L"MIXAR_OLD_LOCATION", program_files_mixar);
      break;
    default:
      mixar_ca_set(h, L"MIXAR_OLD_LOCATION", own.location);
      break;
  }
  mixar_ca_set(h, L"MIXAR_INSPECTED", L"1");
  return ERROR_SUCCESS;
}

UINT __stdcall MixarMarker(MSIHANDLE h)
{
  wchar_t old_location[MIXAR_CA_PATH], root[MIXAR_CA_PATH];
  if (!mixar_ca_get(h, L"MIXAR_OLD_LOCATION", old_location, MIXAR_CA_PATH)) {
    return ERROR_SUCCESS;
  }
  /* Before CostFinalize, so the MixarMovedFrom component's condition sees
   * it: INSTALL_ROOT as given (command line, wizard, MixarInspect), else
   * the scope's default, [ProgramFiles64Folder]Mixar. */
  if (!mixar_ca_get(h, L"INSTALL_ROOT", root, MIXAR_CA_PATH) &&
      mixar_ca_get(h, L"ProgramFiles64Folder", root, MIXAR_CA_PATH))
  {
    mixar_ca_dir(root, MIXAR_CA_PATH);
    wcscat_s(root, MIXAR_CA_PATH, L"Mixar\\");
  }
  if (root[0] && !mixar_path_equal(old_location, root)) {
    mixar_ca_log(h, L"Mixar: moves from %s to %s", old_location, root);
    mixar_ca_set(h, L"MIXAR_MOVED_FROM", old_location);
  }
  return ERROR_SUCCESS;
}

UINT __stdcall MixarRelaunchElevated(MSIHANDLE h)
{
  wchar_t package[MIXAR_CA_PATH], msiexec[MAX_PATH], parameters[MIXAR_CA_PATH + 64];
  SHELLEXECUTEINFOW info = {0};
  mixar_ca_set(h, L"MIXAR_RELAUNCHED", L"");
  if (!mixar_ca_get(h, L"OriginalDatabase", package, MIXAR_CA_PATH) ||
      !GetSystemDirectoryW(msiexec, MAX_PATH))
  {
    return ERROR_SUCCESS;
  }
  wcscat_s(msiexec, MAX_PATH, L"\\msiexec.exe");
  swprintf(parameters, MIXAR_CA_PATH + 64, L"/i \"%s\" MIXAR_ELEVATED_CHILD=1", package);
  info.cbSize = sizeof(info);
  info.fMask = SEE_MASK_NOASYNC;
  info.hwnd = GetForegroundWindow();
  info.lpVerb = L"runas";
  info.lpFile = msiexec;
  info.lpParameters = parameters;
  info.nShow = SW_SHOWNORMAL;
  if (ShellExecuteExW(&info)) {
    mixar_ca_log(h, L"Mixar: continues elevated");
    mixar_ca_set(h, L"MIXAR_RELAUNCHED", L"1");
  }
  else {
    /* 1223: the prompt was declined. Nothing changed; the wizard stays. */
    mixar_ca_log(h, L"Mixar: could not continue elevated (%lu)", GetLastError());
  }
  return ERROR_SUCCESS;
}

/* ------------------------------------------------------------------------ */

#define MIXAR_MAX_PROGIDS 16

static const wchar_t *const mixar_binaries[] = {L"mixar-launcher.exe", L"mixar.exe"};

/* Does the key's open command start one of the binaries in `folder` (with its
 * trailing backslash)? The whole path, not a prefix: a folder's prefix would
 * also match another copy below it, and C:\ every copy. */
static int command_uses(HKEY classes, const wchar_t *key, const wchar_t *folder)
{
  wchar_t path[256], command[MIXAR_CA_PATH], binary[MIXAR_CA_PATH];
  DWORD size = sizeof(command);
  swprintf(path, 256, L"%s\\shell\\open\\command", key);
  if (RegGetValueW(classes, path, NULL, RRF_RT_REG_SZ | RRF_RT_REG_EXPAND_SZ | RRF_NOEXPAND, NULL,
                   command, &size) != ERROR_SUCCESS)
  {
    return 0;
  }
  CharUpperW(command);
  for (int i = 0; i < 2; i++) {
    swprintf(binary, MIXAR_CA_PATH, L"%s%s", folder, mixar_binaries[i]);
    CharUpperW(binary);
    const wchar_t *at = wcsstr(command, binary);
    if (at && (at == command || at[-1] == L'"')) {
      return 1;
    }
  }
  return 0;
}

UINT __stdcall MixarCleanMachineAssociations(MSIHANDLE h)
{
  wchar_t old_dir[MIXAR_CA_PATH], file[MIXAR_CA_PATH];
  wchar_t folder[MIXAR_CA_PATH], name[256], deleted[MIXAR_MAX_PROGIDS][256];
  int deleted_count = 0;
  HKEY classes, hkey;

  if (!mixar_ca_get(h, L"CustomActionData", old_dir, MIXAR_CA_PATH)) {
    return ERROR_SUCCESS;
  }
  mixar_ca_dir(old_dir, MIXAR_CA_PATH);
  /* Another account's copy keeps them. */
  for (int i = 0; i < 2; i++) {
    swprintf(file, MIXAR_CA_PATH, L"%s%s", old_dir, mixar_binaries[i]);
    if (mixar_ca_file_exists(file)) {
      mixar_ca_log(h, L"Mixar: %s is still there - machine file types kept", file);
      return ERROR_SUCCESS;
    }
  }
  if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, L"SOFTWARE\\Classes", 0,
                    KEY_READ | KEY_WRITE | DELETE | KEY_WOW64_64KEY, &classes) != ERROR_SUCCESS)
  {
    return ERROR_SUCCESS;
  }
  wcscpy_s(folder, MIXAR_CA_PATH, old_dir);
  CharUpperW(folder);

  /* The mixar.X.Y ProgIDs whose open command runs the removed copy. */
  for (DWORD i = 0; deleted_count < MIXAR_MAX_PROGIDS; i++) {
    DWORD size = 256;
    if (RegEnumKeyExW(classes, i, name, &size, NULL, NULL, NULL, NULL) != ERROR_SUCCESS) {
      break;
    }
    if (_wcsnicmp(name, L"mixar.", 6) == 0 && command_uses(classes, name, folder)) {
      wcscpy_s(deleted[deleted_count++], 256, name);
    }
  }
  for (int i = 0; i < deleted_count; i++) {
    RegDeleteTreeW(classes, deleted[i]);
    mixar_ca_log(h, L"Mixar: removed HKLM ProgID %s", deleted[i]);
  }
  if (command_uses(classes, L"Applications\\mixar-launcher.exe", folder)) {
    RegDeleteTreeW(classes, L"Applications\\mixar-launcher.exe");
  }
  /* .mixar: its default and Open-with entries for those ProgIDs, then the
   * keys themselves once empty. */
  if (RegOpenKeyExW(classes, L".mixar", 0, KEY_READ | KEY_WRITE | KEY_WOW64_64KEY, &hkey) ==
      ERROR_SUCCESS)
  {
    wchar_t current[256];
    DWORD size = sizeof(current), values = 0, subkeys = 0;
    HKEY open_with;
    if (RegGetValueW(hkey, NULL, NULL, RRF_RT_REG_SZ, NULL, current, &size) == ERROR_SUCCESS) {
      for (int i = 0; i < deleted_count; i++) {
        if (_wcsicmp(current, deleted[i]) == 0) {
          RegDeleteValueW(hkey, NULL);
          break;
        }
      }
    }
    if (RegOpenKeyExW(hkey, L"OpenWithProgids", 0, KEY_READ | KEY_WRITE | KEY_WOW64_64KEY,
                      &open_with) == ERROR_SUCCESS)
    {
      for (int i = 0; i < deleted_count; i++) {
        RegDeleteValueW(open_with, deleted[i]);
      }
      RegQueryInfoKeyW(
          open_with, NULL, NULL, NULL, &subkeys, NULL, NULL, &values, NULL, NULL, NULL, NULL);
      RegCloseKey(open_with);
      if (values == 0 && subkeys == 0) {
        RegDeleteKeyExW(hkey, L"OpenWithProgids", KEY_WOW64_64KEY, 0);
      }
    }
    RegQueryInfoKeyW(hkey, NULL, NULL, NULL, &subkeys, NULL, NULL, &values, NULL, NULL, NULL, NULL);
    RegCloseKey(hkey);
    if (values == 0 && subkeys == 0) {
      RegDeleteKeyExW(classes, L".mixar", KEY_WOW64_64KEY, 0);
      mixar_ca_log(h, L"Mixar: removed HKLM .mixar");
    }
  }
  RegCloseKey(classes);
  if (deleted_count) {
    SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, NULL, NULL);
  }
  return ERROR_SUCCESS;
}
