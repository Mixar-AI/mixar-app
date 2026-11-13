/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * Shared helpers of the installer's custom-action DLL (#2079).
 */

#pragma once

#ifndef WIN32_LEAN_AND_MEAN
#  define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

#include <msi.h>
#include <msidefs.h>
#include <msiquery.h>

#define MIXAR_CA_PATH 1024
#define MIXAR_CA_LIST 4096

/* Program Files from the registry: a per-user install redirects
 * ProgramFiles64Folder into the user's profile. */
#define MIXAR_CA_CURRENT_VERSION_KEY L"SOFTWARE\\Microsoft\\Windows\\CurrentVersion"

/* Property `name` into `buf` (`cap` characters); 1 when it is not empty. */
int mixar_ca_get(MSIHANDLE h, const wchar_t *name, wchar_t *buf, DWORD cap);
void mixar_ca_set(MSIHANDLE h, const wchar_t *name, const wchar_t *value);
/* One "Mixar: ..." line in the verbose MSI log. */
void mixar_ca_log(MSIHANDLE h, const wchar_t *format, ...);
/* Appends a backslash unless `path` already ends with one. */
void mixar_ca_dir(wchar_t *path, size_t cap);
/* A value of HKLM's 64-bit view, read with RegGetValueW's `flags` (RRF_RT_*);
 * 1 when found. The key is opened with KEY_WOW64_64KEY: RRF_SUBKEY_WOW6464KEY
 * exists only for _WIN32_WINNT >= 0x0A00 and Blender builds for 0x0603. */
int mixar_ca_hklm_value(
    const wchar_t *key, const wchar_t *name, DWORD flags, void *out, DWORD *size);
/* A REG_SZ value from HKLM's 64-bit view; 1 when found and not empty. */
int mixar_ca_hklm_string(const wchar_t *key, const wchar_t *name, wchar_t *out, DWORD cap);
int mixar_ca_file_exists(const wchar_t *path);

/* Facts (mixar_msi_facts.c). */
typedef struct MixarOwnProduct {
  int found;
  wchar_t location[MIXAR_CA_PATH]; /* "" when unknown; ends with a backslash. */
} MixarOwnProduct;

/* The component GUID of mixar.exe in this package ({...}), "" when absent:
 * every release since the single install folder shares it. */
void mixar_facts_exe_component(MSIHANDLE h, wchar_t *out, DWORD cap);
/* This context's earlier Mixar, from every Upgrade row that removes one. */
void mixar_facts_own_product(MSIHANDLE h,
                             const wchar_t *component,
                             const wchar_t *program_files,
                             MixarOwnProduct *r_own);
int mixar_facts_machine_product(const wchar_t *upgrade_code);
int mixar_facts_session_matches(MSIHANDLE h, const wchar_t *user_sid);
int mixar_facts_path_policy(void);
/* Does Windows Installer allow installs only with an administrator
 * (DisableMSI 1 or 2, or absent on Windows Server)? 1 when unsure. */
int mixar_facts_installer_policy(MSIHANDLE h);
/* Does another account use the Program Files copy: registered mixar.exe
 * there, or has Mixar's data in its profile? 1 when unsure. Elevated only:
 * other profiles are readable by an administrator alone. */
int mixar_facts_program_files_shared(MSIHANDLE h,
                                     const wchar_t *component,
                                     const wchar_t *user_sid,
                                     const wchar_t *program_files_mixar);
/* Is a file in `folder` (or below it) open in another process? */
int mixar_facts_files_in_use(const wchar_t *folder);
