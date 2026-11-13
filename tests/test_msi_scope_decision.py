# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Where the MSI installs Mixar for the account running it (#2079).

``installer_ca/mixar_msi_scope.c`` is the installer custom action's one
decision, free of Windows headers: these tests compile it with the host's C
compiler and call it, so every row of the table runs here and not only on
the Windows QA box. The rule it carries (product owner): every existing user
moves out of Program Files with at most the one administrator prompt they
get today, and nobody is left worse off than today, so anything that cannot
move cleanly is updated where it is, as every release before #2079 did.
"""

import ctypes
import itertools
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CA_DIR = ROOT / "src" / "release" / "windows" / "installer_ca"

FIELDS = (
    "all_users", "privileged", "system_account", "full_ui", "elevated_child",
    "own_product", "own_location_known", "own_in_program_files", "root_from_command_line",
    "machine_product", "program_files_exe", "session_matches", "path_policy",
    "program_files_shared", "program_files_in_use", "installer_policy",
)

FRESH, KEEP, MOVE, IN_PLACE, IN_PLACE_PF, BESIDE, RELAUNCH = range(7)
REFUSE_SYSTEM, REFUSE_MACHINE, REFUSE_NEEDS_ADMIN = range(7, 10)


class Facts(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int) for name in FIELDS]


@pytest.fixture(scope="module")
def scope(tmp_path_factory):
    compiler = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if not compiler:
        pytest.skip("no C compiler on this host")
    out = tmp_path_factory.mktemp("msi_scope") / "libmixar_msi_scope.so"
    subprocess.run(
        [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
         "-o", str(out), str(CA_DIR / "mixar_msi_scope.c")],
        check=True, capture_output=True,
    )
    lib = ctypes.CDLL(str(out))
    lib.mixar_scope_decide.argtypes = [ctypes.POINTER(Facts),
                                       ctypes.POINTER(ctypes.c_char_p)]
    lib.mixar_scope_decide.restype = ctypes.c_int
    lib.mixar_scope_action_name.restype = ctypes.c_char_p
    lib.mixar_scope_refusal.restype = ctypes.c_char_p
    lib.mixar_path_within.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    lib.mixar_path_equal.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    lib.mixar_pack_guid.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    lib.mixar_profile_of_another_person.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    lib.mixar_profile_folder_maybe_there.argtypes = [ctypes.c_uint, ctypes.c_uint]
    return lib


def _decide(lib, **facts):
    reason = ctypes.c_char_p()
    action = lib.mixar_scope_decide(ctypes.byref(Facts(**facts)), ctypes.byref(reason))
    return action, reason.value.decode()


# This account's Mixar in Program Files, found by the upgrade, with its folder.
OWN_PF = dict(own_product=1, own_location_known=1, own_in_program_files=1,
              program_files_exe=1)
# The update today's app runs: elevated through its helper, as the signed-in user.
ELEVATED_AS_USER = dict(privileged=1, session_matches=1)


def test_this_accounts_program_files_install_moves(scope):
    assert _decide(scope, **OWN_PF, **ELEVATED_AS_USER) == (MOVE, "own_program_files")
    # The wizard's elevated copy decides the same.
    assert _decide(scope, **OWN_PF, **ELEVATED_AS_USER, full_ui=1, elevated_child=1) == (
        MOVE, "own_program_files")


@pytest.mark.parametrize("fact, reason", [
    # Approved with another account's credentials (a standard user's update,
    # Windows 11 Administrator Protection): the copy would land in the
    # approver's profile and the signed-in user would lose theirs.
    ("session_matches", "other_session_user"),
])
def test_an_install_run_as_someone_else_stays_in_place(scope, fact, reason):
    facts = {**OWN_PF, **ELEVATED_AS_USER, fact: 0}
    assert _decide(scope, **facts) == (IN_PLACE, reason)


@pytest.mark.parametrize("fact, reason", [
    ("path_policy", "path_policy"),             # AppLocker / SRP allow apps by folder
    ("program_files_shared", "shared"),         # another account uses that copy
    # A file of the old copy is open in another process: the move's uninstall
    # would stop at a "reboot required" prompt (box run 20261113-002114, holder).
    ("program_files_in_use", "files_in_use"),
    ("system_account", "system_account"),       # a deployment tool updating SYSTEM's own
    # Windows Installer allows installs only with an administrator (DisableMSI
    # 1 or 2, or absent on Windows Server): moved, every update would still
    # need the prompt, so the move gains nothing and the prompts stay.
    ("installer_policy", "installer_policy"),
])
def test_a_move_that_cannot_complete_cleanly_updates_in_place(scope, fact, reason):
    assert _decide(scope, **OWN_PF, **ELEVATED_AS_USER, **{fact: 1}) == (IN_PLACE, reason)


def test_without_elevation_the_wizard_asks_and_a_quiet_install_refuses(scope):
    assert _decide(scope, **OWN_PF, full_ui=1) == (RELAUNCH, "not_elevated")
    # The relaunched copy never relaunches again (no loop) ...
    assert _decide(scope, **OWN_PF, full_ui=1, elevated_child=1) == (
        REFUSE_NEEDS_ADMIN, "not_elevated")
    # ... and a quiet install (the app's helper, IT) gets a clear message.
    assert _decide(scope, **OWN_PF) == (REFUSE_NEEDS_ADMIN, "not_elevated")
    assert scope.mixar_scope_refusal(REFUSE_NEEDS_ADMIN) == b"needs_admin"


def test_another_accounts_program_files_copy(scope):
    # An administrator approving someone else's update: as every release did.
    assert _decide(scope, program_files_exe=1, privileged=1) == (
        IN_PLACE_PF, "other_account")
    assert _decide(scope, program_files_exe=1, privileged=1, session_matches=1) == (
        IN_PLACE_PF, "other_account")
    # Without elevation it cannot touch it: this account gets its own copy.
    assert _decide(scope, program_files_exe=1) == (BESIDE, "not_elevated")
    assert _decide(scope, program_files_exe=1, full_ui=1) == (BESIDE, "not_elevated")


def test_custom_and_per_user_folders_stay(scope):
    own_custom = dict(own_product=1, own_location_known=1)
    assert _decide(scope, **own_custom) == (KEEP, "own_folder")
    assert _decide(scope, **own_custom, **ELEVATED_AS_USER) == (KEEP, "own_folder")
    # Only a folder on the command line moves it.
    assert _decide(scope, **own_custom, root_from_command_line=1) == (FRESH, "command_line")


def test_a_copy_whose_folder_cannot_be_read_is_updated_where_it_is(scope):
    """Only a release before #2079 can lack a readable folder, and every one
    was installed elevated, into Program Files or a folder IT chose: it is
    updated where that release put it (MixarInspect: the old product's
    Uninstall InstallLocation, else Program Files\\Mixar), never moved
    unchecked into the profile."""
    unknown = dict(own_product=1)
    assert _decide(scope, **unknown, **ELEVATED_AS_USER) == (IN_PLACE, "location_unknown")
    assert _decide(scope, **unknown, privileged=1) == (IN_PLACE, "location_unknown")
    # Without an administrator it cannot be written: as a Program Files copy.
    assert _decide(scope, **unknown, full_ui=1) == (RELAUNCH, "not_elevated")
    assert _decide(scope, **unknown) == (REFUSE_NEEDS_ADMIN, "not_elevated")
    # Only a folder on the command line moves it.
    assert _decide(scope, **unknown, privileged=1, root_from_command_line=1) == (
        FRESH, "command_line")


def test_machine_installs(scope):
    # IT's ALLUSERS=1 update keeps the machine install's folder, wherever it is.
    assert _decide(scope, all_users=1, own_product=1, own_location_known=1,
                   privileged=1) == (KEEP, "machine_scope")
    assert _decide(scope, all_users=1, own_product=1, own_location_known=1,
                   root_from_command_line=1) == (FRESH, "")
    assert _decide(scope, all_users=1) == (FRESH, "")
    # A per-user install beside a machine one would be a second copy.
    assert _decide(scope, machine_product=1) == (REFUSE_MACHINE, "machine_product")
    assert _decide(scope, machine_product=1, program_files_exe=1, privileged=1) == (
        REFUSE_MACHINE, "machine_product")


def test_system_without_its_own_mixar_is_refused(scope):
    assert _decide(scope, system_account=1, privileged=1) == (
        REFUSE_SYSTEM, "system_account")
    assert _decide(scope, system_account=1, privileged=1, program_files_exe=1) == (
        REFUSE_SYSTEM, "system_account")


def test_a_fresh_install(scope):
    assert _decide(scope) == (FRESH, "")
    assert _decide(scope, privileged=1, session_matches=1) == (FRESH, "")


def test_every_outcome_is_named_the_way_the_app_reads_it(scope):
    from mixar.modules.common.updates import constants

    actions, reasons, refusals = set(), set(), set()
    for bits in itertools.product((0, 1), repeat=len(FIELDS)):
        action, reason = _decide(scope, **dict(zip(FIELDS, bits)))
        actions.add(scope.mixar_scope_action_name(action).decode())
        refusals.add(scope.mixar_scope_refusal(action).decode())
        if reason:
            reasons.add(reason)
        # Only the three refusals stop the install, and a refusal is never
        # what an elevated install as the signed-in user gets for its own copy.
        assert (action >= REFUSE_SYSTEM) == bool(scope.mixar_scope_refusal(action))
    assert actions == set(constants.MSI_SCOPE_ACTIONS)
    assert reasons == set(constants.MSI_SCOPE_REASONS)
    assert refusals - {""} == set(constants.MSI_REFUSALS)


def test_nobody_with_their_own_copy_is_refused_when_elevated(scope):
    """Today's app always elevates: none of its users may be turned away."""
    for bits in itertools.product((0, 1), repeat=len(FIELDS)):
        facts = dict(zip(FIELDS, bits))
        if facts["all_users"] or not facts["own_product"] or not facts["privileged"]:
            continue
        action, _reason = _decide(scope, **facts)
        assert action < REFUSE_SYSTEM, facts


def test_folder_comparisons(scope):
    within, equal = scope.mixar_path_within, scope.mixar_path_equal
    assert within(r"C:\Program Files\Mixar", "C:\\Program Files\\")
    assert within("c:\\program files\\mixar\\", r"C:\Program Files")
    assert within(r"C:\Program Files", r"C:\Program Files")
    assert not within(r"C:\Program Files (x86)\Mixar", r"C:\Program Files")
    assert not within(r"C:\Program", r"C:\Program Files")
    assert not within(r"C:\Users\José\AppData", "")
    assert within(r"C:\Users\Дмитрий\AppData\Local", r"C:\Users\Дмитрий")
    assert equal(r"C:\Program Files\Mixar\\", "c:/program files/mixar")
    assert not equal(r"C:\Program Files\Mixar", r"C:\Program Files")
    assert not equal("", "")


def _packed(guid):
    """Windows Installer's packed GUID, written out independently."""
    hexes = guid.strip("{}").replace("-", "")
    head = hexes[7::-1] + hexes[11:7:-1] + hexes[15:11:-1]
    tail = "".join(hexes[i + 1] + hexes[i] for i in range(16, 32, 2))
    return (head + tail).upper()


def test_guids_are_packed_as_the_installer_registry_keys_name_them(scope):
    from mixar.modules.common.updates import constants

    out = ctypes.create_unicode_buffer(33)
    assert scope.mixar_pack_guid(constants.MSI_UPGRADE_CODE, out)
    assert out.value == "0FC5582633DC1A750B37F9C3527B326C" == _packed(
        constants.MSI_UPGRADE_CODE)
    for _ in range(20):
        guid = "{%s}" % str(uuid.uuid4()).upper()
        assert scope.mixar_pack_guid(guid.lower(), out) and out.value == _packed(guid)
    for bad in ("", "62855CF0-CD33-57A1-B073-9F3C25B723C6",
                "{62855CF0-CD33-57A1-B073-9F3C25B723CG}", "{62855CF0CD33-57A1-B073-9F3C25B723C6-}"):
        assert not scope.mixar_pack_guid(bad, out), bad


def test_only_another_persons_profile_counts(scope):
    """Mixar's data in another profile (``ProfileList``) means someone else
    uses the Program Files copy: only profiles people sign in with count,
    never the installing account's own or a system profile."""
    me = "S-1-5-21-111-222-333-1001"
    other = scope.mixar_profile_of_another_person
    assert other("S-1-5-21-111-222-333-1002", me)  # another local or domain account
    assert other("S-1-5-21-444-555-666-1001", me)  # same RID, another machine or domain
    assert other("S-1-12-1-4-5-6-7", me)  # a Microsoft Entra ID account
    assert not other(me, me)
    assert not other(me.lower(), me)
    # Windows keeps "<SID>.bak" for a profile it could not load: same account.
    assert not other(me + ".bak", me) and not other(me + ".BAK", me)
    assert other("S-1-5-21-111-222-333-1002.bak", me)
    # SYSTEM, LocalService, NetworkService, a service's own profile; Default
    # and Public are ProfileList values, never keys, but are not people either.
    for system in ("S-1-5-18", "S-1-5-19", "S-1-5-20", "S-1-5-80-1-2-3-4-5", "Default",
                   "Public", "", "S-1-5-21"):
        assert not other(system, me), system
    # Without the installing account's SID every person's profile counts.
    assert other(me, "")


def test_a_profile_that_cannot_be_read_counts_as_using_the_copy(scope):
    """GetFileAttributesW on ``<profile>\\AppData\\{Roaming,Local}\\Mixar``:
    only Windows saying it is not there clears it; anything else is unsure,
    and unsure keeps the copy in place."""
    there = scope.mixar_profile_folder_maybe_there
    invalid = 0xFFFFFFFF
    assert there(0x10, 0)  # FILE_ATTRIBUTE_DIRECTORY
    assert there(0x12, 0)  # ... hidden
    assert not there(invalid, 2)  # ERROR_FILE_NOT_FOUND
    assert not there(invalid, 3)  # ERROR_PATH_NOT_FOUND: the profile folder is gone
    for error in (5, 21, 53, 1920, 0):  # access denied, not ready, network, cannot access
        assert there(invalid, error), error
