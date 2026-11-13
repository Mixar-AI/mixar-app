/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * Where the MSI installs Mixar for the account running it (#2079): the one
 * decision of the installer's custom action, kept free of Windows headers so
 * the unit tests compile and call it on any host (tests/test_msi_scope_decision.py).
 */

#pragma once

#include <wchar.h>

#ifdef __cplusplus
extern "C" {
#endif

#ifdef _WIN32
#  define MIXAR_SCOPE_API
#else
#  define MIXAR_SCOPE_API __attribute__((visibility("default")))
#endif

/* What MixarInspect found; every field is 0 or 1. */
typedef struct MixarScopeFacts {
  int all_users;            /* ALLUSERS resolved to 1: a machine install. */
  int privileged;           /* The install runs with administrator rights. */
  int system_account;       /* It runs as SYSTEM (UserSID S-1-5-18). */
  int full_ui;              /* UILevel 5: the wizard, which can ask for approval. */
  int elevated_child;       /* The install MixarRelaunchElevated started. */
  int own_product;          /* FindRelatedProducts found this account's Mixar. */
  int own_location_known;   /* ... and where it is installed. */
  int own_in_program_files; /* ... under Program Files. */
  int root_from_command_line; /* INSTALL_ROOT came on the command line. */
  int machine_product;      /* A Mixar is installed for all users. */
  int program_files_exe;    /* Program Files\Mixar\mixar.exe exists. */
  int session_matches;      /* The signed-in user is the installing account. */
  int path_policy;          /* AppLocker / SRP rules that allow apps by folder. */
  int program_files_shared; /* Another account's Mixar is registered there too, or
                             * another person's profile holds Mixar's data. */
  int program_files_in_use; /* A file of this account's Program Files copy is open
                             * in another process. */
  int installer_policy;     /* Windows Installer allows installs only with an
                             * administrator: DisableMSI 1 or 2, or absent on
                             * Windows Server. */
} MixarScopeFacts;

typedef enum MixarScopeAction {
  /* The scope's default folder (or INSTALL_ROOT from the command line). */
  MIXAR_SCOPE_FRESH = 0,
  /* The product's own folder: a custom per-user folder, or a machine install. */
  MIXAR_SCOPE_KEEP,
  /* Out of Program Files into the user's profile. */
  MIXAR_SCOPE_MOVE,
  /* This account's Program Files install, updated where it is. */
  MIXAR_SCOPE_IN_PLACE,
  /* Program Files\Mixar, which another account installed, updated where it
   * is: what every release before #2079 did. */
  MIXAR_SCOPE_IN_PLACE_PROGRAM_FILES,
  /* A copy for this account beside another account's Program Files one. */
  MIXAR_SCOPE_BESIDE,
  /* The wizard asks for administrator approval and runs elevated. */
  MIXAR_SCOPE_RELAUNCH,
  MIXAR_SCOPE_REFUSE_SYSTEM,
  MIXAR_SCOPE_REFUSE_MACHINE,
  MIXAR_SCOPE_REFUSE_NEEDS_ADMIN,
} MixarScopeAction;

/** The action for these facts; `*r_reason` names the fact that decided it. */
MIXAR_SCOPE_API int mixar_scope_decide(const MixarScopeFacts *facts, const char **r_reason);
/** Stable name of an action: MIXAR_SCOPE_ACTION in the MSI log. */
MIXAR_SCOPE_API const char *mixar_scope_action_name(int action);
/** MIXAR_SCOPE_REFUSAL for a refusing action, "" otherwise. */
MIXAR_SCOPE_API const char *mixar_scope_refusal(int action);

/** Is `path` the folder `root` or inside it? Case-insensitive for ASCII,
 * either may end with a backslash. */
MIXAR_SCOPE_API int mixar_path_within(const wchar_t *path, const wchar_t *root);
/** Do both name the same folder? */
MIXAR_SCOPE_API int mixar_path_equal(const wchar_t *a, const wchar_t *b);

/** Windows Installer's packed form of a GUID ("{01234567-89AB-...}" becomes
 * "76543210BA98..."), as its registry keys use. `out` holds 33 characters.
 * Returns 0 when `guid` is not a braced GUID. */
MIXAR_SCOPE_API int mixar_pack_guid(const wchar_t *guid, wchar_t *out);

/** Is the ProfileList key `profile_sid` another person's profile than
 * `user_sid`'s? Only accounts people sign in with count: local and domain
 * accounts (S-1-5-21-...) and Microsoft Entra ID ones (S-1-12-1-...), never
 * SYSTEM, LocalService, NetworkService or a service's own profile. Windows
 * keeps "<SID>.bak" for a profile it could not load: the same account. */
MIXAR_SCOPE_API int mixar_profile_of_another_person(const wchar_t *profile_sid,
                                                    const wchar_t *user_sid);
/** What GetFileAttributesW (`attributes`, then GetLastError's `error`) says
 * of a Mixar folder in another profile: 0 only when Windows says it is not
 * there (ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND); 1 when it is, or when
 * it could not be read (unsure, so the copy stays where it is). */
MIXAR_SCOPE_API int mixar_profile_folder_maybe_there(unsigned int attributes,
                                                     unsigned int error);

#ifdef __cplusplus
}
#endif
