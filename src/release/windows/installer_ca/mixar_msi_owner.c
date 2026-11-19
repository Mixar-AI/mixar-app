/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * MixarOwnInstallFolder (#2154): before an update in place from the user's
 * own token, make the installing user the owner of every file and folder
 * of the copy being updated.
 *
 * Windows Installer re-applies an overwritten file's security descriptor,
 * owner included, to the new copy. A Program Files install that an elevated
 * 4.4.x update moved into %LocalAppData%\Programs\Mixar (#2079) left its
 * files owned by BUILTIN\Administrators, and a limited token cannot set that
 * owner: the next update failed on the first changed unversioned file
 * (Info 1310 "System error 0", then 1304 and 1603) and rolled back, every
 * time. The user's inherited Full control includes WRITE_OWNER, which lets
 * a token make itself the owner without any privilege; nothing else of the
 * descriptor changes. The content stays as it is, so a rollback of the
 * update leaves a working copy, now the user's.
 *
 * Immediate, impersonated, scheduled by WIX.template only for a copy kept
 * or updated in place by a token that is not privileged. Reparse points
 * (links, junctions, mount points) are neither changed nor followed. A path
 * it cannot change is logged and skipped: the update then fails as before
 * #2154, no worse. Always returns success.
 */

#include "mixar_msi_ca.h"

#include <aclapi.h>
#include <stdio.h>
#include <stdlib.h>

/* Long paths: \\?\ plus the deepest path a Mixar tree has, with room. */
#define MIXAR_OWNER_PATH 32768
#define MIXAR_OWNER_LOGGED_FAILURES 10

typedef struct MixarOwnerWalk {
  MSIHANDLE h;
  PSID user;
  wchar_t *path; /* MIXAR_OWNER_PATH characters, the walk's current path. */
  unsigned changed, already, skipped_links, failed;
} MixarOwnerWalk;

static PSID token_user(void)
{
  HANDLE token = NULL;
  DWORD size = 0;
  TOKEN_USER *info;
  PSID sid = NULL;
  if (!OpenThreadToken(GetCurrentThread(), TOKEN_QUERY, TRUE, &token) &&
      !OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token))
  {
    return NULL;
  }
  GetTokenInformation(token, TokenUser, NULL, 0, &size);
  info = size ? (TOKEN_USER *)malloc(size) : NULL;
  if (info && GetTokenInformation(token, TokenUser, info, size, &size)) {
    const DWORD length = GetLengthSid(info->User.Sid);
    sid = malloc(length);
    if (sid && !CopySid(length, sid, info->User.Sid)) {
      free(sid);
      sid = NULL;
    }
  }
  free(info);
  CloseHandle(token);
  return sid;
}

static void own_one(MixarOwnerWalk *walk)
{
  PSID owner = NULL;
  PSECURITY_DESCRIPTOR sd = NULL;
  DWORD status = GetNamedSecurityInfoW(
      walk->path, SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION, &owner, NULL, NULL, NULL, &sd);
  if (status == ERROR_SUCCESS && owner && EqualSid(owner, walk->user)) {
    walk->already++;
    LocalFree(sd);
    return;
  }
  LocalFree(sd);
  if (status == ERROR_SUCCESS) {
    /* SetFileSecurityW writes the owner alone: unlike SetNamedSecurityInfoW
     * it never re-propagates inherited entries through a folder. */
    SECURITY_DESCRIPTOR only_owner;
    if (InitializeSecurityDescriptor(&only_owner, SECURITY_DESCRIPTOR_REVISION) &&
        SetSecurityDescriptorOwner(&only_owner, walk->user, FALSE) &&
        SetFileSecurityW(walk->path, OWNER_SECURITY_INFORMATION, &only_owner))
    {
      walk->changed++;
      return;
    }
    status = GetLastError();
  }
  if (++walk->failed <= MIXAR_OWNER_LOGGED_FAILURES) {
    mixar_ca_log(walk->h, L"Mixar: could not own %s (error %lu)", walk->path, status);
  }
}

/* Every entry below walk->path (a folder), depth first. */
static void own_tree(MixarOwnerWalk *walk)
{
  const size_t base = wcslen(walk->path);
  WIN32_FIND_DATAW found;
  HANDLE search;
  if (base + 3 >= MIXAR_OWNER_PATH) {
    walk->failed++;
    return;
  }
  wcscpy_s(walk->path + base, MIXAR_OWNER_PATH - base, L"\\*");
  search = FindFirstFileExW(
      walk->path, FindExInfoBasic, &found, FindExSearchNameMatch, NULL, FIND_FIRST_EX_LARGE_FETCH);
  walk->path[base] = L'\0';
  if (search == INVALID_HANDLE_VALUE) {
    return;
  }
  do {
    const wchar_t *name = found.cFileName;
    const size_t length = wcslen(name);
    if (wcscmp(name, L".") == 0 || wcscmp(name, L"..") == 0) {
      continue;
    }
    if (found.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) {
      walk->skipped_links++;
      continue;
    }
    if (base + 1 + length >= MIXAR_OWNER_PATH) {
      walk->failed++;
      continue;
    }
    walk->path[base] = L'\\';
    wcscpy_s(walk->path + base + 1, MIXAR_OWNER_PATH - base - 1, name);
    own_one(walk);
    if (found.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
      own_tree(walk);
    }
    walk->path[base] = L'\0';
  } while (FindNextFileW(search, &found));
  FindClose(search);
}

UINT __stdcall MixarOwnInstallFolder(MSIHANDLE h)
{
  wchar_t root[MIXAR_CA_PATH];
  MixarOwnerWalk walk = {h};
  DWORD attributes;
  ULONGLONG started;
  size_t length;

  if (!mixar_ca_get(h, L"INSTALL_ROOT", root, MIXAR_CA_PATH)) {
    return ERROR_SUCCESS;
  }
  length = wcslen(root);
  while (length > 3 && root[length - 1] == L'\\') {
    root[--length] = L'\0';
  }
  attributes = GetFileAttributesW(root);
  if (attributes == INVALID_FILE_ATTRIBUTES || !(attributes & FILE_ATTRIBUTE_DIRECTORY) ||
      (attributes & FILE_ATTRIBUTE_REPARSE_POINT))
  {
    mixar_ca_log(h, L"Mixar: %s is not a plain folder - owner left as it is", root);
    return ERROR_SUCCESS;
  }
  walk.user = token_user();
  walk.path = malloc(MIXAR_OWNER_PATH * sizeof(wchar_t));
  if (!walk.user || !walk.path) {
    mixar_ca_log(h, L"Mixar: no user token - owner left as it is");
    free(walk.user);
    free(walk.path);
    return ERROR_SUCCESS;
  }
  started = GetTickCount64();
  swprintf(walk.path, MIXAR_OWNER_PATH, L"\\\\?\\%s", root);
  own_one(&walk);
  own_tree(&walk);
  mixar_ca_log(h,
               L"Mixar: owner of %s set to the installing user: %u changed, %u already, "
               L"%u links skipped, %u failed, %llu ms",
               root,
               walk.changed,
               walk.already,
               walk.skipped_links,
               walk.failed,
               GetTickCount64() - started);
  free(walk.user);
  free(walk.path);
  return ERROR_SUCCESS;
}
