# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Windows installer is per-user by default (#2079).

One dual-purpose MSI: a double-click or an update installs for the current
user in %LocalAppData%\\Programs\\Mixar with no administrator prompt, IT
installs for everyone with ALLUSERS=1. Where an install goes is the custom
action's decision (``installer_ca``; its table runs in
``tests/test_msi_scope_decision.py``). These guards keep the authoring that
wires it in: the actions are scheduled where their facts exist, a refusal
stops before any change, the wizard asks for approval instead of refusing,
and the names the in-app updater reads from the log and the registry match.
The conditions themselves run only on Windows (the QA box's peruser_win).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIX_DIR = ROOT / "src" / "release" / "windows" / "installer_wix"
CA_DIR = ROOT / "src" / "release" / "windows" / "installer_ca"
WIX_TEMPLATE = WIX_DIR / "WIX.template"
WIXUI = WIX_DIR / "WixUI_Blender.wxs"
PACKAGING_CMAKE = ROOT / "src" / "build_files" / "cmake" / "packaging.cmake"


def _template() -> str:
    return WIX_TEMPLATE.read_text(encoding="utf-8")


def _windows_block() -> str:
    cmake = PACKAGING_CMAKE.read_text(encoding="utf-8")
    return cmake[cmake.index("if(WIN32)"):cmake.index("include(CPack)")]


def _ca(name) -> str:
    return (CA_DIR / name).read_text(encoding="utf-8")


def _component(template, component_id) -> str:
    body = template[template.index(f'<Component Id="{component_id}"'):]
    return body[:body.index("</Component>")]


def _sequence(template, name) -> str:
    body = template[template.index(f"<{name}>"):]
    return body[:body.index(f"</{name}>")]


def test_the_package_is_dual_purpose_and_per_user_by_default():
    block = _windows_block()
    assert 'set(CPACK_WIX_PROPERTY_ALLUSERS "2")' in block
    assert 'set(CPACK_WIX_PROPERTY_MSIINSTALLPERUSER "1")' in block
    template = _template()
    # The scope comes from the command line only; a LUA-marked package
    # ignores MSIINSTALLPERUSER and turns ALLUSERS=1 into error 1925.
    assert '<Package InstallerVersion="301" Compressed="yes"/>' in template
    assert "InstallPrivileges" not in template and "InstallScope" not in template
    assert not re.search(r'<SetProperty Id="ALLUSERS"', template)
    assert not re.search(r'<Property Id="ALLUSERS"', template)


def test_the_custom_action_dll_is_built_and_embedded():
    block = _windows_block()
    assert "add_subdirectory(\n    ${CMAKE_SOURCE_DIR}/release/windows/installer_ca" in block
    assert '<Binary Id=\\"MixarMsiCa\\" SourceFile=\\"${_mixar_msi_ca_dll}\\"/>' in block
    assert "${MIXAR_MSI_CA_WXS}" in block[block.index("set(CPACK_WIX_EXTRA_SOURCES"):]
    cmake = _ca("CMakeLists.txt")
    # It runs before Mixar's runtime exists: static C runtime.
    assert 'MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>"' in cmake
    assert 'string(REGEX REPLACE "/MDd?( |$)" ""' in cmake
    exports = set(_ca("mixar_msi_ca.def").split()[3:])
    assert exports == {"MixarInspect", "MixarMarker", "MixarRelaunchElevated",
                       "MixarCleanMachineAssociations"}
    template = _template() + WIXUI.read_text(encoding="utf-8")
    for entry in exports:
        assert f'BinaryKey="MixarMsiCa" DllEntry="{entry}"' in re.sub(r"\s+", " ", template)


def test_the_decision_runs_once_after_the_searches_in_either_sequence():
    template = _template()
    inspect = ('<Custom Action="MixarInspect" After="AppSearch"><![CDATA[NOT Installed AND '
               'NOT MIXAR_INSPECTED]]></Custom>')
    assert inspect in _sequence(template, "InstallUISequence")
    assert inspect in _sequence(template, "InstallExecuteSequence")
    # The wizard's decision (and the folder the user chose) reaches the
    # execute sequence, which then does not decide again.
    for prop in ("INSTALL_ROOT", "MIXAR_INSPECTED", "MIXAR_SCOPE_ACTION", "MIXAR_SCOPE_REASON",
                 "MIXAR_SCOPE_REFUSAL", "MIXAR_OLD_LOCATION", "MIXAR_ELEVATED_CHILD"):
        assert f'<Property Id="{prop}" Secure="yes"/>' in template, prop
    assert 'L"MIXAR_INSPECTED", L"1"' in _ca("mixar_msi_ca.c")


def test_without_the_dll_the_old_folder_is_kept():
    """A custom action that cannot run must leave Mixar where it is, as the
    CPack search did before #2079."""
    template = _template()
    assert ('<SetProperty Id="INSTALL_ROOT" Action="MixarKeepWithoutInspect" '
            'Value="[MIXAR_ARP_LOCATION]"\n            After="MixarInspect" Sequence="both">'
            '<![CDATA[NOT Installed AND NOT MIXAR_INSPECTED AND NOT INSTALL_ROOT AND '
            'MIXAR_ARP_LOCATION]]></SetProperty>') in template
    assert "Uninstall\\[WIX_UPGRADE_DETECTED]" in template
    assert all(f'Id="{action}" BinaryKey="MixarMsiCa"' in template for action in (
        "MixarInspect", "MixarMarker", "MixarRelaunchElevated"))
    assert template.count('Return="ignore"') >= 8
    assert "return ERROR_SUCCESS;" in _ca("mixar_msi_ca.c")
    assert "ERROR_INSTALL_FAILURE" not in _ca("mixar_msi_ca.c")


def test_every_refusal_stops_at_launch_conditions():
    template = _template()
    for value in ("system", "machine", "needs_admin"):
        assert re.search(
            r'<Condition Message="[^"]+">\s*<!\[CDATA\[Installed OR MIXAR_SCOPE_REFUSAL <> "%s"\]\]>'
            % value, template), value
    messages = dict(re.findall(
        r'<Condition Message="([^"]+)">\s*<!\[CDATA\[Installed OR MIXAR_SCOPE_REFUSAL <> "(\w+)"',
        template))
    messages = {value: text for text, value in messages.items()}
    # Each says what to do instead, so none can loop.
    assert "ALLUSERS=1" in messages["machine"] and "ALLUSERS=1" in messages["system"]
    assert "Double-click the installer" in messages["needs_admin"]
    # No refusal is decided anywhere but the custom action.
    assert '<SetProperty Id="MIXAR_SCOPE_REFUSAL"' not in template
    assert "other_account" not in template


def test_program_files_is_read_from_the_registry():
    """A per-user install redirects ProgramFiles64Folder into the profile."""
    template = _template()
    search = template[template.index('<Property Id="MIXAR_PROGRAM_FILES">'):]
    search = search[:search.index("</Property>")]
    assert 'Name="ProgramW6432Dir"' in search and 'Root="HKLM"' in search
    assert '"ProgramW6432Dir"' in _ca("mixar_msi_ca.c")
    assert "ProgramFiles64Folder" not in _ca("mixar_msi_facts.c")


def test_the_facts_come_from_windows_installer_not_from_folders():
    facts = _ca("mixar_msi_facts.c")
    # Every major-upgrade row (the UpgradeCode and the legacy per-version
    # ones), so several found products or a legacy one keep their folder.
    assert "SELECT `ActionProperty`, `Attributes` FROM `Upgrade`" in facts
    assert "msidbUpgradeAttributesOnlyDetect" in facts
    assert 'MsiGetProductInfoW(code, L"InstallLocation"' in facts
    # A machine install is found by its UpgradeCode, not its Start menu folder.
    assert "SOFTWARE\\\\Classes\\\\Installer\\\\UpgradeCodes\\\\%s" in facts
    assert "Common Programs" not in facts + _template()
    # Who is signed in, and whether rules allow programs by folder.
    assert "ProcessIdToSessionId" in facts and "WTSQuerySessionInformation" in facts
    assert "SrpV2\\\\Exe" in facts and "Safer\\\\CodeIdentifiers" in facts
    # A file of the old copy held open by another process: opened with no
    # sharing, file by file, never through a link out of the folder.
    scan = facts[facts.index("static int in_use_below"):]
    assert "CreateFileW(\n        path, GENERIC_READ, 0," in scan
    assert "ERROR_SHARING_VIOLATION" in scan and "FILE_ATTRIBUTE_REPARSE_POINT" in scan
    ca = _ca("mixar_msi_ca.c")
    assert "f.program_files_in_use = mixar_facts_files_in_use(own.location);" in ca


def test_the_installer_policy_is_read_as_windows_applies_it():
    """``DisableMSI`` 1 or 2 refuses installs without an administrator, and
    absent it behaves as 1 on Windows Server (``MsiNTProductType`` other than
    1): after a move every update would still need the prompt, so the copy
    is updated in place. A value that is not a number counts as set (unsure,
    so in place), as ``win_msi.user_installs_blocked_by_policy`` reads it."""
    facts = _ca("mixar_msi_facts.c")
    policy = facts[facts.index("int mixar_facts_installer_policy(MSIHANDLE h)"):]
    policy = policy[:policy.index("\n}\n")]
    assert 'L"SOFTWARE\\\\Policies\\\\Microsoft\\\\Windows\\\\Installer"' in policy
    assert 'dword_value(key, L"DisableMSI", &value)' in policy and "return value != 0;" in policy
    assert 'mixar_ca_hklm_value(key, L"DisableMSI", RRF_RT_ANY' in policy
    assert ('!mixar_ca_get(h, L"MsiNTProductType", product_type, 8) || '
            'wcscmp(product_type, L"1") != 0') in policy
    ca = _ca("mixar_msi_ca.c")
    assert "f.installer_policy = mixar_facts_installer_policy(h);" in ca


def test_a_copy_kept_where_it_is_keeps_a_folder():
    """In place with no readable folder (``location_unknown``): the old
    product's Uninstall ``InstallLocation`` (AppSearch's
    ``MIXAR_ARP_LOCATION``), else ``Program Files\\Mixar``, as every release
    before #2079 installed it. An empty ``INSTALL_ROOT`` would fall back to the
    per-user default and move the copy unchecked."""
    ca = _ca("mixar_msi_ca.c")
    where = ca[ca.index("wchar_t where[MIXAR_CA_PATH];"):ca.index("switch (action) {")]
    assert "wcscpy_s(where, MIXAR_CA_PATH, own.location);" in where
    assert 'mixar_ca_get(h, L"MIXAR_ARP_LOCATION", where, MIXAR_CA_PATH)' in where
    assert "wcscpy_s(where, MIXAR_CA_PATH, program_files_mixar);" in where
    keep = ca[ca.index("    case MIXAR_SCOPE_KEEP:"):ca.index("    case MIXAR_SCOPE_IN_PLACE_PROGRAM_FILES:")]
    assert 'mixar_ca_set(h, L"INSTALL_ROOT", where);' in keep
    assert 'mixar_ca_set(h, L"MIXAR_OLD_LOCATION", where);' in keep


def test_a_copy_beside_another_accounts_moved_nothing():
    """``beside`` installs this account's own copy next to another account's
    Program Files one, which stays. Nothing moved, so no ``moved_from``:
    with it the app reported ``moved_from_program_files``, read another
    account's result from the shared staging folder once as its own, and
    repointed this account's pins away from the copy it ran."""
    ca = _ca("mixar_msi_ca.c")
    switch = ca[ca.index("  switch (action) {"):ca.index('mixar_ca_set(h, L"MIXAR_INSPECTED", L"1");')]
    assert "MIXAR_SCOPE_BESIDE" not in switch
    default = switch[switch.index("    default:"):]
    # This account has no product of its own there: own.location is empty,
    # and MixarMarker sets nothing without an old location.
    assert 'mixar_ca_set(h, L"MIXAR_OLD_LOCATION", own.location);' in default
    marker = ca[ca.index("UINT __stdcall MixarMarker"):]
    assert ('if (!mixar_ca_get(h, L"MIXAR_OLD_LOCATION", old_location, MIXAR_CA_PATH)) {\n'
            '    return ERROR_SUCCESS;') in marker


def test_another_persons_mixar_data_keeps_the_copy_in_place():
    """The copy is shared when another account registered mixar.exe there, or
    when another person's profile holds Mixar's data (GHOST's user folder
    ``AppData\\Roaming\\Mixar``; caches, bytecode and update staging in
    ``AppData\\Local\\Mixar``): before #2079 the Program Files copy was the
    only one, so they used it. Read in MixarInspect's elevated branch only,
    where an administrator may read every profile; a profile or list that
    cannot be read counts (unsure, so in place)."""
    facts = _ca("mixar_msi_facts.c")
    profiles = facts[facts.index("static int other_profile_has_mixar("):]
    profiles = profiles[:profiles.index("\n}\n")]
    assert 'L"SOFTWARE\\\\Microsoft\\\\Windows NT\\\\CurrentVersion\\\\ProfileList"' in profiles
    assert 'L"ProfileImagePath"' in profiles and "ExpandEnvironmentStringsW" in profiles
    assert 'L"\\\\AppData\\\\Roaming\\\\Mixar"' in profiles
    assert 'L"\\\\AppData\\\\Local\\\\Mixar"' in profiles
    assert "mixar_profile_of_another_person(sid, user_sid)" in profiles
    assert "mixar_profile_folder_maybe_there(attributes" in profiles
    assert "ERROR_NO_MORE_ITEMS" in profiles
    shared = facts[facts.index("int mixar_facts_program_files_shared("):]
    shared = shared[:shared.index("\n}\n")]
    assert "other_profile_has_mixar(h, user_sid)" in shared
    ca = _ca("mixar_msi_ca.c")
    block = ca[ca.index("if (!f.all_users && own.found && f.own_in_program_files && f.privileged)"):]
    block = block[:block.index("\n  }\n")]
    assert "mixar_facts_program_files_shared(\n        h, component, user_sid" in block


def test_what_the_move_cannot_see_is_written_down():
    """Limits the installer accepts rather than handles (round-2 review):
    the files-in-use scan runs before anything changes, so a file opened
    after it still brings the 1610 box; WDAC and per-user SRP are not
    detected; a failed move is tried again by the next update, with one
    prompt."""
    doc = " ".join((ROOT / "docs" / "modules" / "self-update.md").read_text(
        encoding="utf-8").split())
    limits = doc[doc.index("**What the move cannot see.**"):]
    limits = limits[:limits.index(" - **")]
    for fact in ("1610", "after the scan", "HKCU\\Software\\Policies\\Microsoft\\Windows\\Safer",
                 "WDAC", "rolls back", "next update tries again", "one prompt"):
        assert fact in limits, fact
    facts = _ca("mixar_msi_facts.c")
    assert "HKEY_CURRENT_USER" not in facts  # per-user SRP really is not read


def test_the_move_marker_is_written_whenever_the_folder_changes():
    template = _template()
    assert ('<Custom Action="MixarMarker" Before="CostFinalize"><![CDATA[NOT Installed]]>'
            '</Custom>') in _sequence(template, "InstallExecuteSequence")
    component = _component(template, "MixarMovedFrom")
    assert "<Condition>MIXAR_MOVED_FROM</Condition>" in component
    assert 'Root="HKCU"' in component
    assert 'Name="moved_from" Type="string" Value="[MIXAR_MOVED_FROM]"' in component
    assert '<ComponentRef Id="MixarMovedFrom"/>' in template
    ca = _ca("mixar_msi_ca.c")
    marker = ca[ca.index("UINT __stdcall MixarMarker"):ca.index("UINT __stdcall MixarRelaunch")]
    assert "!mixar_path_equal(old_location, root)" in marker
    assert 'mixar_ca_set(h, L"MIXAR_MOVED_FROM", old_location)' in marker


def test_an_elevated_install_never_runs_the_launcher_it_installed():
    template = _template()
    component = _component(template, "MixarRegisterPending")
    assert "<Condition>Privileged AND NOT ALLUSERS</Condition>" in component
    assert 'Name="register_pending" Type="integer" Value="1"' in component
    assert '<ComponentRef Id="MixarRegisterPending"/>' in template
    assert ('<Custom Action="RegisterMixarUser" After="InstallFiles">NOT (REMOVE="ALL") AND '
            'NOT ALLUSERS AND NOT Privileged</Custom>') in template


def test_the_wizard_asks_for_approval_instead_of_refusing():
    template = _template()
    wixui = WIXUI.read_text(encoding="utf-8")
    assert ('<Publish Dialog="WelcomeDlg" Control="Next" Event="NewDialog" '
            'Value="MixarElevateDlg"><![CDATA[NOT Installed AND MIXAR_SCOPE_ACTION = '
            '"relaunch"]]></Publish>') in wixui
    dialog = wixui[wixui.index('<Dialog Id="MixarElevateDlg"'):]
    dialog = dialog[:dialog.index("</Dialog>")]
    assert 'ElevationShield="yes"' in dialog
    assert '<Publish Event="DoAction" Value="MixarRelaunchElevated" Order="1">1</Publish>' in dialog
    assert ('<Publish Event="EndDialog" Value="Return" Order="2">MIXAR_RELAUNCHED</Publish>'
            in dialog)
    # The wizard that handed over installs nothing and launches nothing.
    assert "<ExecuteAction><![CDATA[NOT MIXAR_RELAUNCHED]]></ExecuteAction>" in _sequence(
        template, "InstallUISequence")
    assert template.count("and NOT MIXAR_RELAUNCHED and NOT MIXAR_ELEVATED_CHILD</Publish>") == 2
    # The elevated copy is marked, so it can never ask again (no loop).
    ca = _ca("mixar_msi_ca.c")
    assert 'L"/i \\"%s\\" MIXAR_ELEVATED_CHILD=1"' in ca and 'L"runas"' in ca
    assert 'flag(h, L"MIXAR_ELEVATED_CHILD")' in ca


def test_the_approval_dialog_is_true_whatever_the_elevated_copy_decides():
    """The elevated copy decides again: it moves Mixar, or (another account
    uses the copy, a policy, a held file, approval by another account, an
    unreadable folder) updates it where it is, and then every later update
    asks again. So the dialog promises neither, and names no folder:
    MIXAR_OLD_LOCATION is empty when Windows Installer cannot name it."""
    wixui = WIXUI.read_text(encoding="utf-8")
    dialog = wixui[wixui.index('<Dialog Id="MixarElevateDlg"'):]
    dialog = dialog[:dialog.index("</Dialog>")]
    texts = " ".join(re.findall(r'Text="([^"]*)"', dialog))
    for promise in ("Move Mixar", "needed once", "never need", "[MIXAR_OLD_LOCATION]"):
        assert promise not in texts, promise
    assert "to your user folder when it can" in texts
    assert "where it is" in texts and "If you choose No, nothing changes." in texts


def test_the_elevated_wizard_never_starts_anything():
    """The wizard's elevated copy (MIXAR_ELEVATED_CHILD) runs with an
    administrator's full token, and over the shoulder as that administrator:
    Mixar started from it would run elevated from a folder the user can
    write, or as the other account on the user's desktop; the Discord link
    would open a browser the same way. Its exit dialog offers neither and
    says where to start Mixar instead."""
    template = _template()
    finish = dict(re.findall(
        r'<Publish Dialog="MixarExitDialog"\s+Control="Finish"\s+Event="DoAction"\s+'
        r'Value="(\w+)"\s+Order="\d">([^<]+)</Publish>', template))
    assert set(finish) == {"LaunchMixar", "LaunchDiscord"}
    for condition in finish.values():
        assert condition.endswith("and NOT MIXAR_ELEVATED_CHILD"), condition
    wixui = WIXUI.read_text(encoding="utf-8")
    dialog = wixui[wixui.index('<Dialog Id="MixarExitDialog"'):]
    dialog = dialog[:dialog.index("</Dialog>")]
    for box in ("LaunchCheckBox", "DiscordCheckBox"):
        control = dialog[dialog.index(f'<Control Id="{box}"'):]
        control = control[:control.index("</Control>")]
        assert ('<Condition Action="show">NOT Installed AND NOT MIXAR_RELAUNCHED AND '
                'NOT MIXAR_ELEVATED_CHILD</Condition>') in control, box
    note = dialog[dialog.index('<Control Id="ElevatedText"'):]
    note = note[:note.index("</Control>")]
    assert 'Hidden="yes"' in note and "Start menu" in note
    assert '<Condition Action="show">MIXAR_ELEVATED_CHILD</Condition>' in note


def test_an_unelevated_administrator_is_not_privileged():
    """The wizard's own sequence sets Privileged for an administrator's
    UAC-filtered token (it could elevate); this install will not, so the
    decision must relaunch it elevated, not move (box run 20261113-024449)."""
    ca = _ca("mixar_msi_ca.c")
    assert "type == TokenElevationTypeLimited" in ca
    assert 'f.privileged = flag(h, L"Privileged") && !limited;' in ca
    assert 'mixar_ca_set(h, L"MIXAR_LIMITED_TOKEN", L"1");' in ca


def test_without_elevation_the_wizard_offers_no_admin_only_folder():
    """Program Files, Program Files (x86) and Windows: the folders only an
    administrator may write that the updater knows (``win_scope.program_files_dirs``,
    ``WindowsFolder``). Both Program Files come from the registry, as a
    per-user install redirects ``ProgramFilesFolder`` too."""
    wixui = WIXUI.read_text(encoding="utf-8")
    assert ('Property="MIXAR_DIR_NEEDS_ADMIN" Value="1" Order="5"><![CDATA[NOT ALLUSERS AND '
            '(NOT Privileged OR MIXAR_LIMITED_TOKEN) AND ((MIXAR_PROGRAM_FILES AND INSTALL_ROOT ~<< '
            'MIXAR_PROGRAM_FILES) OR (MIXAR_PROGRAM_FILES_X86 AND INSTALL_ROOT ~<< '
            'MIXAR_PROGRAM_FILES_X86) OR (WindowsFolder AND INSTALL_ROOT ~<< WindowsFolder))]]>'
            ) in wixui
    template = _template()
    search = template[template.index('<Property Id="MIXAR_PROGRAM_FILES_X86">'):]
    search = search[:search.index("</Property>")]
    assert 'Root="HKLM"' in search and 'Key="SOFTWARE\\Microsoft\\Windows\\CurrentVersion"' in search
    assert 'Name="ProgramFilesDir (x86)"' in search and 'Win64="yes"' in search
    assert ('Event="SpawnDialog" Value="MixarAdminDirDlg" Order="6">MIXAR_DIR_NEEDS_ADMIN'
            in wixui)
    assert ('Value="VerifyReadyDlg" Order="7">(WIXUI_DONTVALIDATEPATH OR '
            'WIXUI_INSTALLDIR_VALID="1") AND NOT MIXAR_DIR_NEEDS_ADMIN</Publish>') in wixui
    # Cleared first, so going back and choosing again works.
    assert 'Property="MIXAR_DIR_NEEDS_ADMIN" Value="{}" Order="4">1</Publish>' in wixui


def test_machine_file_types_are_removed_only_with_the_last_program_files_copy():
    template = _template()
    action = template[template.index('<CustomAction Id="MixarCleanMachineAssociations"'):]
    action = action[:action.index("/>")]
    assert 'Execute="deferred" Impersonate="no"' in action
    condition = "NOT Installed AND NOT ALLUSERS AND Privileged AND MIXAR_MOVED_FROM"
    assert (f'<Custom Action="MixarCleanMachineAssociations" After="RemoveExistingProducts">'
            f'<![CDATA[{condition}]]></Custom>') in template
    assert (f'<SetProperty Id="MixarCleanMachineAssociations" Value="[MIXAR_MOVED_FROM]"\n'
            f'            After="MixarMarker" Sequence="execute"><![CDATA[{condition}]]>'
            ) in template
    ca = _ca("mixar_msi_ca.c")
    clean = ca[ca.index("UINT __stdcall MixarCleanMachineAssociations"):]
    assert "mixar_ca_file_exists(file)" in clean  # another account's copy keeps them
    assert 'command_uses(classes, name, folder)' in clean
    # The open command must start that copy's own binary: a folder prefix
    # would also take another copy below it, and C:\\ every copy.
    uses = ca[ca.index("static int command_uses"):ca.index("UINT __stdcall MixarCleanMachineAssociations")]
    assert 'mixar_binaries[] = {L"mixar-launcher.exe", L"mixar.exe"}' in ca
    assert 'swprintf(binary, MIXAR_CA_PATH, L"%s%s", folder, mixar_binaries[i])' in uses
    assert "at == command || at[-1] == L'\"'" in uses
    assert "wcsstr(command, folder)" not in uses


def test_removing_a_copy_updated_in_place_takes_its_machine_file_types():
    """A copy kept or updated in place keeps the HKLM association its
    release registered (register-allusers); the released uninstall removed
    it, and this package unregisters per user only, so the same action runs
    for this product's own folder after its files are gone (box run
    20261113-034911 found one left)."""
    template = _template()
    action = template[template.index('<CustomAction Id="MixarCleanMachineAssociationsOnRemove"'):]
    action = re.sub(r"\s+", " ", action[:action.index("/>")])
    assert 'DllEntry="MixarCleanMachineAssociations" Execute="deferred" Impersonate="no"' in action
    condition = '(NOT UPGRADINGPRODUCTCODE) AND (REMOVE="ALL") AND NOT ALLUSERS AND Privileged'
    execute = _sequence(template, "InstallExecuteSequence")
    assert (f'<Custom Action="MixarCleanMachineAssociationsOnRemove" After="RemoveFiles">'
            f'<![CDATA[{condition}]]></Custom>') in execute
    assert (f'<SetProperty Id="MixarCleanMachineAssociationsOnRemove" Value="[INSTALL_ROOT]"\n'
            f'            Before="MixarCleanMachineAssociationsOnRemove" Sequence="execute">'
            f'<![CDATA[{condition}]]></SetProperty>') in template
    # Any folder, not only Program Files: a custom folder's release
    # registered it there too.
    ca = _ca("mixar_msi_ca.c")
    clean = ca[ca.index("UINT __stdcall MixarCleanMachineAssociations"):]
    assert "program_files" not in clean


def test_the_app_reads_the_names_the_installer_writes():
    from mixar.modules.common.updates import constants

    template = _template()
    ca = _ca("mixar_msi_ca.c")
    assert constants.MSI_REFUSAL_PROPERTY == "MIXAR_SCOPE_REFUSAL"
    assert f'L"{constants.MSI_REFUSAL_PROPERTY}"' in ca
    assert 'L"MIXAR_SCOPE_ACTION"' in ca and 'L"MIXAR_SCOPE_REASON"' in ca
    assert set(constants.MSI_REFUSALS) == {"machine", "needs_admin", "system"}
    assert f'Name="{constants.MOVED_FROM_VALUE}"' in template
    assert f'Name="{constants.REGISTER_PENDING_VALUE}"' in template
    assert constants.MIXAR_REGISTRY_KEY == "Software\\Mixar\\Mixar"
