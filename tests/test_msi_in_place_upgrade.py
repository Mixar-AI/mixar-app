# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Windows updates install the new MSI over the old one (#2060).

The old product is removed after the new one installs and REINSTALLMODE is
the default omus, so only files that differ are written. That is correct
only because package.bat forces every versioned file to be replaced before
the MSI is signed, and because the template clears the shortcuts CPack names
after the previous MAJOR.MINOR: these guards keep the pieces in step.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIX_TEMPLATE = ROOT / "src" / "release" / "windows" / "installer_wix" / "WIX.template"
PACKAGE_BAT = ROOT / "scripts" / "windows" / "package.bat"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
FORCE_SCRIPT = ROOT / "scripts" / "ci" / "force-msi-file-overwrite.ps1"
PACKAGING_CMAKE = ROOT / "src" / "build_files" / "cmake" / "packaging.cmake"


def _template() -> str:
    return WIX_TEMPLATE.read_text(encoding="utf-8")


def test_old_product_is_removed_after_the_new_one_installs():
    assert re.search(r'<MajorUpgrade\s+Schedule="afterInstallExecute"', _template())


def test_reinstall_mode_is_the_default_and_restart_manager_is_off():
    template = _template()
    # 'amus' rewrote every file on every update.
    assert 'Id="REINSTALLMODE"' not in template
    assert '<Property Id="MSIRESTARTMANAGERCONTROL" Value="Disable" />' in template


def test_upgrades_do_not_keep_the_old_folder():
    """CPack's INSTALL_ROOT / FindInstallLocation AppSearch put every upgrade
    back into the old product's folder, so a Program Files install could never
    move (#2079). Setting ARPINSTALLLOCATION is the CPack switch that drops it;
    the template then owns INSTALL_ROOT (declared once: a second
    Property:INSTALL_ROOT fails light.exe with LGHT0091) and the SetProperty."""
    template = _template()
    cmake = PACKAGING_CMAKE.read_text(encoding="utf-8")
    assert re.search(r'set\(CPACK_WIX_PROPERTY_ARPINSTALLLOCATION\s+"\[INSTALL_ROOT\]"\)', cmake)
    assert len(re.findall(r'<Property\s+Id="INSTALL_ROOT"', template)) == 1
    assert '<Property Id="INSTALL_ROOT" Secure="yes"/>' in template
    assert 'FindInstallLocation' not in template
    assert '<SetProperty Id="ARPINSTALLLOCATION" Value="[INSTALL_ROOT]" After="CostFinalize"/>' in template


def test_earlier_version_shortcuts_are_removed_on_install():
    template = _template()
    patterns = ["Mixar ?.?.lnk", "Mixar ?.??.lnk", "Mixar ??.?.lnk", "Mixar ??.??.lnk"]
    removals = re.findall(r"<RemoveFile\b[^>]*>", template)
    menu = [r for r in removals if 'Directory="' not in r]
    desktop = [r for r in removals if 'Directory="DesktopFolder"' in r]
    for found in (menu, desktop):
        assert sorted(re.search(r'Name="([^"]+)"', r).group(1) for r in found) == sorted(patterns)
        assert all('On="install"' in r for r in found)
    assert "*" not in "".join(removals)  # a user's own "Mixar something.lnk" stays
    assert '<ComponentRef Id="MixarStaleShortcuts"/>' in template
    assert re.search(r'<DirectoryRef Id="PROGRAM_MENU_FOLDER">\s*<Component Id="MixarStaleShortcuts"', template)


def test_package_bat_forces_versioned_files_before_signing():
    bat = PACKAGE_BAT.read_text(encoding="utf-8")
    cpack = bat.index("cpack %CPACK_ARGS%")
    force = bat.index(r"scripts\ci\force-msi-file-overwrite.ps1")
    assert cpack < force < bat.index("Installer Created Successfully")
    assert "exit /b 1" in bat[force:bat.index("Installer Created Successfully")]
    # One owner: the release job signs what package.bat produced.
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    steps = re.findall(r"^      - name: (.+)$", workflow, re.M)
    package = steps.index("Package MSI")
    assert steps[package + 1] == "Sign MSI (Azure Trusted Signing)"
    assert "force-msi-file-overwrite" not in workflow
    script = FORCE_SCRIPT.read_text(encoding="utf-8")
    assert "'65535.65535.65535.65535'" in script
    assert "SignerCertificate" in script  # refuses an MSI that is already signed
    # Every binary is forced, with or without a version resource (a binary that loses its version
    # resource would otherwise never replace the versioned copy on disk), and a forced row loses its
    # MsiFileHash (a hash describes an unversioned file).
    assert "$Binary = '\\.(exe|dll|pyd)$'" in script
    assert "-not $row.Version" in script and "$row.Name -match $Binary" in script
    assert "DELETE FROM `MsiFileHash`" in script


def test_register_runs_only_when_installing():
    # The old product's uninstall runs after the new install (afterInstallExecute), with the
    # launcher still on disk: an unconditional register action would register a second time.
    template = _template()
    # ... and an elevated per-user install leaves it to the app (#2079 review).
    assert ('<Custom Action="RegisterMixarUser" After="InstallFiles">'
            'NOT (REMOVE="ALL") AND NOT ALLUSERS AND NOT Privileged</Custom>') in template
    assert ('<Custom Action="RegisterMixarMachine" After="RegisterMixarUser">'
            'NOT (REMOVE="ALL") AND ALLUSERS</Custom>') in template
    assert ('<Custom Action="UnRegisterMixarUser" Before="RemoveFiles">'
            '(NOT UPGRADINGPRODUCTCODE) AND (REMOVE="ALL") AND NOT ALLUSERS</Custom>') in template
    assert ('<Custom Action="UnRegisterMixarMachine" After="UnRegisterMixarUser">'
            '(NOT UPGRADINGPRODUCTCODE) AND (REMOVE="ALL") AND ALLUSERS</Custom>') in template
