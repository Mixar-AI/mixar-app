/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * What MixarInspect reads about this machine before the scope decision
 * (#2079). Every reader answers "no" or "unknown" on any failure, and each
 * unknown makes the decision keep Mixar where it is, as every release before
 * #2079 did.
 */

#include "mixar_msi_ca.h"
#include "mixar_msi_scope.h"

#include <sddl.h>
#include <stdio.h>
#include <wtsapi32.h>

void mixar_facts_exe_component(MSIHANDLE h, wchar_t *out, DWORD cap)
{
  out[0] = L'\0';
  MSIHANDLE db = MsiGetActiveDatabase(h);
  MSIHANDLE view = 0, rec = 0;
  if (!db) {
    return;
  }
  if (MsiDatabaseOpenViewW(db,
                           L"SELECT `Component`.`ComponentId` FROM `Component`, `File` "
                           L"WHERE `File`.`Component_` = `Component`.`Component` "
                           L"AND `File`.`File` = 'CM_FP_mixar.exe'",
                           &view) == ERROR_SUCCESS &&
      MsiViewExecute(view, 0) == ERROR_SUCCESS && MsiViewFetch(view, &rec) == ERROR_SUCCESS)
  {
    DWORD n = cap;
    if (MsiRecordGetStringW(rec, 1, out, &n) != ERROR_SUCCESS) {
      out[0] = L'\0';
    }
  }
  if (rec) {
    MsiCloseHandle(rec);
  }
  if (view) {
    MsiCloseHandle(view);
  }
  MsiCloseHandle(db);
}

/* Where `code` is installed: its InstallLocation, else the folder of its
 * mixar.exe (Windows Installer's own record of the file). */
static int product_location(const wchar_t *code, const wchar_t *component, wchar_t *out)
{
  DWORD n = MIXAR_CA_PATH;
  out[0] = L'\0';
  if (MsiGetProductInfoW(code, L"InstallLocation", out, &n) == ERROR_SUCCESS &&
      out[0])
  {
    mixar_ca_dir(out, MIXAR_CA_PATH);
    return 1;
  }
  if (component[0]) {
    n = MIXAR_CA_PATH;
    const INSTALLSTATE state = MsiGetComponentPathW(code, component, out, &n);
    wchar_t *slash = wcsrchr(out, L'\\');
    if (state == INSTALLSTATE_LOCAL && slash) {
      slash[1] = L'\0';
      return 1;
    }
  }
  out[0] = L'\0';
  return 0;
}

void mixar_facts_own_product(MSIHANDLE h,
                             const wchar_t *component,
                             const wchar_t *program_files,
                             MixarOwnProduct *r_own)
{
  r_own->found = 0;
  r_own->location[0] = L'\0';
  MSIHANDLE db = MsiGetActiveDatabase(h);
  MSIHANDLE view = 0, rec = 0;
  if (!db) {
    return;
  }
  /* MajorUpgrade's WIX_UPGRADE_DETECTED and every legacy MIXARLEGACY_*
   * property; each may list several product codes. Detect-only rows
   * (WIX_DOWNGRADE_DETECTED) remove nothing. */
  if (MsiDatabaseOpenViewW(db, L"SELECT `ActionProperty`, `Attributes` FROM `Upgrade`", &view) ==
          ERROR_SUCCESS &&
      MsiViewExecute(view, 0) == ERROR_SUCCESS)
  {
    while (MsiViewFetch(view, &rec) == ERROR_SUCCESS) {
      wchar_t property[96], codes[MIXAR_CA_LIST];
      DWORD n = 96;
      const int attributes = MsiRecordGetInteger(rec, 2);
      const int found = MsiRecordGetStringW(rec, 1, property, &n) == ERROR_SUCCESS &&
                        !(attributes & msidbUpgradeAttributesOnlyDetect) &&
                        mixar_ca_get(h, property, codes, MIXAR_CA_LIST);
      MsiCloseHandle(rec);
      rec = 0;
      if (!found) {
        continue;
      }
      for (wchar_t *code = codes; code && *code;) {
        wchar_t *next = wcschr(code, L';');
        if (next) {
          *next++ = L'\0';
        }
        wchar_t location[MIXAR_CA_PATH];
        r_own->found = 1;
        if (product_location(code, component, location)) {
          mixar_ca_log(h, L"Mixar: earlier product %s (%s) in %s", code, property, location);
          /* The Program Files one is the one that decides; keep the first. */
          if (!r_own->location[0] || (mixar_path_within(location, program_files) &&
                                      !mixar_path_within(r_own->location, program_files)))
          {
            wcscpy_s(r_own->location, MIXAR_CA_PATH, location);
          }
        }
        else {
          mixar_ca_log(h, L"Mixar: earlier product %s (%s), location unknown", code, property);
        }
        code = next;
      }
    }
  }
  if (view) {
    MsiCloseHandle(view);
  }
  MsiCloseHandle(db);
}

int mixar_facts_machine_product(const wchar_t *upgrade_code)
{
  wchar_t packed[33], key[128];
  HKEY hkey;
  DWORD values = 0;
  if (!mixar_pack_guid(upgrade_code, packed)) {
    return 0;
  }
  swprintf(key, 128, L"SOFTWARE\\Classes\\Installer\\UpgradeCodes\\%s", packed);
  if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, key, 0, KEY_READ | KEY_WOW64_64KEY, &hkey) !=
      ERROR_SUCCESS)
  {
    return 0;
  }
  RegQueryInfoKeyW(hkey, NULL, NULL, NULL, NULL, NULL, NULL, &values, NULL, NULL, NULL, NULL);
  RegCloseKey(hkey);
  return values > 0;
}

/* ------------------------------------------------------------------------ */

static DWORD session_id(MSIHANDLE h)
{
  DWORD session = 0;
  wchar_t pid[32];
  if (ProcessIdToSessionId(GetCurrentProcessId(), &session) && session != 0) {
    return session;
  }
  /* The custom-action server may run in session 0; the msiexec that
   * started the install runs where the user is. */
  if (mixar_ca_get(h, L"ClientProcessId", pid, 32) &&
      ProcessIdToSessionId(wcstoul(pid, NULL, 10), &session))
  {
    return session;
  }
  return 0;
}

int mixar_facts_session_matches(MSIHANDLE h, const wchar_t *user_sid)
{
  const DWORD session = session_id(h);
  LPWSTR name = NULL, domain = NULL;
  DWORD bytes = 0;
  int matches = 0;
  if (session == 0 || !user_sid[0] ||
      !WTSQuerySessionInformationW(
          WTS_CURRENT_SERVER_HANDLE, session, WTSUserName, &name, &bytes) ||
      !WTSQuerySessionInformationW(
          WTS_CURRENT_SERVER_HANDLE, session, WTSDomainName, &domain, &bytes) ||
      !name[0])
  {
    mixar_ca_log(h, L"Mixar: the signed-in user of session %lu is unknown", session);
    goto done;
  }

  /* By SID: the session user's name, looked up. */
  {
    wchar_t account[512], found_domain[256];
    BYTE sid[SECURITY_MAX_SID_SIZE];
    DWORD sid_size = sizeof(sid), domain_size = 256;
    SID_NAME_USE use;
    LPWSTR text = NULL;
    swprintf(account, 512, L"%s\\%s", domain, name);
    if (LookupAccountNameW(NULL, account, sid, &sid_size, found_domain, &domain_size, &use) &&
        ConvertSidToStringSidW(sid, &text))
    {
      matches = _wcsicmp(text, user_sid) == 0;
      LocalFree(text);
    }
  }
  /* By name: the installing account's SID, looked up (an Entra ID account's
   * name may not resolve the other way). */
  if (!matches) {
    PSID sid = NULL;
    wchar_t sid_name[256], sid_domain[256];
    DWORD name_size = 256, domain_size = 256;
    SID_NAME_USE use;
    if (ConvertStringSidToSidW(user_sid, &sid)) {
      if (LookupAccountSidW(NULL, sid, sid_name, &name_size, sid_domain, &domain_size, &use)) {
        matches = _wcsicmp(sid_name, name) == 0 && _wcsicmp(sid_domain, domain) == 0;
      }
      LocalFree(sid);
    }
  }
  mixar_ca_log(h, L"Mixar: session %lu user %s\\%s, installing account %s: %s", session,
               domain, name, user_sid, matches ? L"same" : L"different");
done:
  if (name) {
    WTSFreeMemory(name);
  }
  if (domain) {
    WTSFreeMemory(domain);
  }
  return matches;
}

/* ------------------------------------------------------------------------ */

static int subkey_count(const wchar_t *path)
{
  HKEY hkey;
  DWORD subkeys = 0;
  if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, path, 0, KEY_READ | KEY_WOW64_64KEY, &hkey) !=
      ERROR_SUCCESS)
  {
    return 0;
  }
  RegQueryInfoKeyW(hkey, NULL, NULL, NULL, &subkeys, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
  RegCloseKey(hkey);
  return (int)subkeys;
}

static int dword_value(const wchar_t *path, const wchar_t *name, DWORD *r_value)
{
  DWORD size = sizeof(*r_value);
  return mixar_ca_hklm_value(path, name, RRF_RT_REG_DWORD, r_value, &size);
}

int mixar_facts_path_policy(void)
{
  /* AppLocker executable rules, from Group Policy and as Windows applies
   * them: enforced unless EnforcementMode is 0 (audit only). Their default
   * rules allow Program Files and Windows, not the user's profile. */
  static const wchar_t *const applocker[] = {
      L"SOFTWARE\\Policies\\Microsoft\\Windows\\SrpV2\\Exe",
      L"SYSTEM\\CurrentControlSet\\Control\\Srp\\Gp\\Exe",
  };
  for (int i = 0; i < 2; i++) {
    DWORD mode = 1;
    if (subkey_count(applocker[i]) > 0 &&
        (!dword_value(applocker[i], L"EnforcementMode", &mode) || mode != 0))
    {
      return 1;
    }
  }
  /* Software Restriction Policies: everything disallowed by default, or a
   * disallowed path rule (hardening guides block %LocalAppData%). */
  DWORD level = 0x40000;
  if (dword_value(L"SOFTWARE\\Policies\\Microsoft\\Windows\\Safer\\CodeIdentifiers",
                  L"DefaultLevel",
                  &level) &&
      level == 0)
  {
    return 1;
  }
  return subkey_count(L"SOFTWARE\\Policies\\Microsoft\\Windows\\Safer\\CodeIdentifiers\\0\\Paths") >
         0;
}

int mixar_facts_installer_policy(MSIHANDLE h)
{
  /* As Windows Installer applies DisableMSI (win_msi.py reads it the same
   * way): 0 lets anyone install, 1 only an administrator (non-managed apps),
   * 2 nobody. */
  static const wchar_t key[] = L"SOFTWARE\\Policies\\Microsoft\\Windows\\Installer";
  wchar_t product_type[8];
  DWORD value = 0, size = 0;
  if (dword_value(key, L"DisableMSI", &value)) {
    return value != 0;
  }
  if (mixar_ca_hklm_value(key, L"DisableMSI", RRF_RT_ANY, NULL, &size)) {
    return 1; /* Set, but not a number: unsure, so in place. */
  }
  /* Absent: Windows Server (MsiNTProductType 2 or 3) behaves as 1. */
  return !mixar_ca_get(h, L"MsiNTProductType", product_type, 8) || wcscmp(product_type, L"1") != 0;
}

/* ------------------------------------------------------------------------ */

/* Mixar's data in another person's profile: GHOST's user folder
 * (AppData\Roaming\Mixar) and the caches, bytecode and update staging
 * (AppData\Local\Mixar). Before #2079 the Program Files copy was the only
 * one, so whoever has them ran it. MixarInspect reads this elevated, where an
 * administrator may read every profile; a list, profile or folder that
 * cannot be read counts (unsure, so the copy stays where it is). */
static int other_profile_has_mixar(MSIHANDLE h, const wchar_t *user_sid)
{
  static const wchar_t *const folders[] = {L"\\AppData\\Roaming\\Mixar",
                                           L"\\AppData\\Local\\Mixar"};
  wchar_t sid[256], raw[MIXAR_CA_PATH], path[MIXAR_CA_PATH + 32];
  HKEY list;
  int found = 0;
  if (RegOpenKeyExW(HKEY_LOCAL_MACHINE,
                    L"SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\ProfileList",
                    0,
                    KEY_READ | KEY_WOW64_64KEY,
                    &list) != ERROR_SUCCESS)
  {
    mixar_ca_log(h, L"Mixar: the profile list cannot be read");
    return 1;
  }
  for (DWORD i = 0; !found; i++) {
    DWORD sid_size = 256, size = sizeof(raw), expanded = 0;
    const LSTATUS status = RegEnumKeyExW(list, i, sid, &sid_size, NULL, NULL, NULL, NULL);
    if (status == ERROR_NO_MORE_ITEMS) {
      break;
    }
    if (status != ERROR_SUCCESS) {
      mixar_ca_log(h, L"Mixar: the profile list cannot be read (%ld)", (long)status);
      found = 1;
      break;
    }
    if (!mixar_profile_of_another_person(sid, user_sid)) {
      continue;
    }
    if (RegGetValueW(list, sid, L"ProfileImagePath",
                     RRF_RT_REG_SZ | RRF_RT_REG_EXPAND_SZ | RRF_NOEXPAND, NULL, raw,
                     &size) == ERROR_SUCCESS)
    {
      expanded = ExpandEnvironmentStringsW(raw, path, MIXAR_CA_PATH);
    }
    if (expanded == 0 || expanded > MIXAR_CA_PATH) {
      mixar_ca_log(h, L"Mixar: the folder of profile %s cannot be read", sid);
      found = 1;
      break;
    }
    const size_t len = wcslen(path);
    for (int j = 0; j < 2 && !found; j++) {
      wcscpy_s(path + len, MIXAR_CA_PATH + 32 - len, folders[j]);
      const DWORD attributes = GetFileAttributesW(path);
      const DWORD error = attributes == INVALID_FILE_ATTRIBUTES ? GetLastError() : 0;
      if (mixar_profile_folder_maybe_there(attributes, error)) {
        mixar_ca_log(h, L"Mixar: %s is there or cannot be read (%lu)", path, error);
        found = 1;
      }
    }
  }
  RegCloseKey(list);
  return found;
}

int mixar_facts_program_files_shared(MSIHANDLE h,
                                     const wchar_t *component,
                                     const wchar_t *user_sid,
                                     const wchar_t *program_files_mixar)
{
  wchar_t packed[33], sid[256], key[512], name[64], data[MIXAR_CA_PATH];
  HKEY user_data, hkey;
  int shared = 0;
  if (mixar_pack_guid(component, packed) &&
      RegOpenKeyExW(HKEY_LOCAL_MACHINE,
                    L"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Installer\\UserData",
                    0,
                    KEY_READ | KEY_WOW64_64KEY,
                    &user_data) == ERROR_SUCCESS)
  {
    /* Every account's (and SYSTEM's) registration of mixar.exe: one at the
     * Program Files copy, other than this account's, is another user of it. */
    for (DWORD i = 0; !shared; i++) {
      DWORD sid_size = 256;
      if (RegEnumKeyExW(user_data, i, sid, &sid_size, NULL, NULL, NULL, NULL) != ERROR_SUCCESS) {
        break;
      }
      if (_wcsicmp(sid, user_sid) == 0) {
        continue;
      }
      swprintf(key, 512, L"%s\\Components\\%s", sid, packed);
      if (RegOpenKeyExW(user_data, key, 0, KEY_READ | KEY_WOW64_64KEY, &hkey) != ERROR_SUCCESS) {
        continue;
      }
      for (DWORD j = 0; !shared; j++) {
        DWORD name_size = 64, data_size = sizeof(data) - sizeof(wchar_t), type = 0;
        if (RegEnumValueW(hkey, j, name, &name_size, NULL, &type, (BYTE *)data, &data_size) !=
            ERROR_SUCCESS)
        {
          break;
        }
        if (type != REG_SZ) {
          continue;
        }
        data[data_size / sizeof(wchar_t)] = L'\0';
        if (data[0] && data[1] == L'?') {
          data[1] = L':';
        }
        shared = mixar_path_within(data, program_files_mixar);
      }
      RegCloseKey(hkey);
    }
    RegCloseKey(user_data);
  }
  if (shared) {
    mixar_ca_log(h, L"Mixar: another account registered %s", program_files_mixar);
  }
  return shared || other_profile_has_mixar(h, user_sid);
}

/* ------------------------------------------------------------------------ */

/* `path` holds a folder ending in a backslash, `len` characters long, with
 * room for MIXAR_CA_PATH characters. */
static int in_use_below(wchar_t *path, size_t len, int depth)
{
  WIN32_FIND_DATAW found;
  HANDLE find;
  int in_use = 0;
  if (depth > 32 || len + 2 >= MIXAR_CA_PATH) {
    return 0;
  }
  wcscpy_s(path + len, MIXAR_CA_PATH - len, L"*");
  find = FindFirstFileW(path, &found);
  if (find == INVALID_HANDLE_VALUE) {
    return 0;
  }
  do {
    const size_t n = wcslen(found.cFileName);
    if (wcscmp(found.cFileName, L".") == 0 || wcscmp(found.cFileName, L"..") == 0 ||
        (found.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) || len + n + 2 >= MIXAR_CA_PATH)
    {
      continue; /* Never out of the folder through a link. */
    }
    wcscpy_s(path + len, MIXAR_CA_PATH - len, found.cFileName);
    if (found.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
      wcscpy_s(path + len + n, MIXAR_CA_PATH - len - n, L"\\");
      in_use = in_use_below(path, len + n + 1, depth + 1);
      continue;
    }
    /* Opening it with no sharing at all fails while any process has it open
     * (a loaded DLL too), which is what the uninstall's check finds. */
    HANDLE file = CreateFileW(
        path, GENERIC_READ, 0, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file != INVALID_HANDLE_VALUE) {
      CloseHandle(file);
    }
    else {
      const DWORD error = GetLastError();
      in_use = error == ERROR_SHARING_VIOLATION || error == ERROR_LOCK_VIOLATION;
    }
  } while (!in_use && FindNextFileW(find, &found));
  FindClose(find);
  return in_use;
}

int mixar_facts_files_in_use(const wchar_t *folder)
{
  wchar_t path[MIXAR_CA_PATH];
  size_t len = wcslen(folder);
  if (len == 0 || len + 2 >= MIXAR_CA_PATH) {
    return 0;
  }
  wcscpy_s(path, MIXAR_CA_PATH, folder);
  if (path[len - 1] != L'\\') {
    path[len++] = L'\\';
    path[len] = L'\0';
  }
  return in_use_below(path, len, 0);
}
