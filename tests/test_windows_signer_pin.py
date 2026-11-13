# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Windows installs nobody asked for pin the running app's own signer
(issue 2079, after the install-on-quit verify contract).

``verify`` says ``VERIFIED`` for any validly signed MSI when it cannot read
the running app's signature as ``Valid`` (an unsigned dev build, a broken
PowerShell), pinning only that MSI's certificate. A per-user install needs
no prompt, so without more an unsigned app would install another
publisher's package on quit or at launch:

- ``win_signer`` reads the running app's signer once, off the main thread;
- ``silent_refusal`` refuses on Windows while it is not known ``Valid``;
- ``begin_install`` refuses an install nobody asked for without it and
  hands its subject to the helper, whose re-checks require it exactly.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from update_launch_fixtures import staged_fixture  # noqa: F401 - fixture

import pytest

from mixar.modules.common.updates.constants import TRIGGER_CLICK, TRIGGER_LAUNCH, TRIGGER_QUIT
from mixar.modules.common.updates.core import (
    app_paths,
    install_flow,
    install_gate,
    installer,
    silent_install,
    staged_record,
    verify,
    win_helper_ps,
    win_installer,
    win_signer,
)

SUBJECT = "CN=MIXAR INC, O=MIXAR INC, L=Lewes, S=Delaware, C=US"
EXE = r"C:\Users\qa\AppData\Local\Programs\Mixar\mixar.exe"
INSTALL_DIR = r"C:\Users\qa\AppData\Local\Programs\Mixar"


@pytest.fixture(autouse=True)
def fresh_signer():
    win_signer._reset_for_tests()
    yield
    win_signer._reset_for_tests()


def _app_signed(monkeypatch, answer):
    calls = []
    monkeypatch.setattr(verify, "_authenticode", lambda path: calls.append(path) or answer)
    win_signer.read(EXE)
    return calls


# ---------------------------------------------------------------------------
# Reading the running app's signer
# ---------------------------------------------------------------------------


def test_the_app_s_signer_is_read_once_per_session(monkeypatch):
    calls = _app_signed(monkeypatch, ("Valid", SUBJECT, "AB12"))

    assert win_signer.read(EXE) == ("Valid", SUBJECT, "AB12")
    assert calls == [EXE]
    assert win_signer.app_subject() == SUBJECT
    assert win_signer.silent_refusal() == ""


@pytest.mark.parametrize("answer", [
    ("NotSigned", "", ""),
    ("HashMismatch", SUBJECT, "AB12"),
    ("UnknownError", SUBJECT, "AB12"),
    ("Valid", "", ""),
])
def test_an_app_not_validly_signed_has_no_subject_to_pin(monkeypatch, answer):
    _app_signed(monkeypatch, answer)

    assert win_signer.app_subject() == ""
    assert "not validly signed" in win_signer.silent_refusal()


def test_a_read_the_tool_could_not_answer_is_tried_again(monkeypatch):
    calls = _app_signed(monkeypatch, None)
    assert win_signer.app_subject() == ""

    monkeypatch.setattr(verify, "_authenticode", lambda path: calls.append(path) or (
        "Valid", SUBJECT, "AB12"))
    assert win_signer.read(EXE)[1] == SUBJECT
    assert len(calls) == 2


def test_not_read_yet_is_not_signed_and_never_blocks():
    assert win_signer.app_subject() == ""
    assert win_signer.silent_refusal() != ""


# ---------------------------------------------------------------------------
# The silent gate
# ---------------------------------------------------------------------------


def _per_user_eligibility():
    location = app_paths.InstallLocation(INSTALL_DIR, True, needs_elevation=False,
                                         scope="per_user", elevate=False)
    return installer.Eligibility(True, location=location, extension=".msi")


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(install_gate, "silent_blocker", lambda eligibility: "")
    monkeypatch.setattr(silent_install.os, "name", "nt")


def test_an_unsigned_windows_app_never_installs_by_itself(windows, monkeypatch):
    """The MSI verified (its own certificate pinned), but this app is not
    signed: nothing ties the package to this app's publisher."""
    _app_signed(monkeypatch, ("NotSigned", "", ""))

    refusal = silent_install.silent_refusal(
        _per_user_eligibility(), verified=True, signer="AB12")

    assert "not validly signed" in refusal


def test_a_validly_signed_windows_app_installs_by_itself(windows, monkeypatch):
    _app_signed(monkeypatch, ("Valid", SUBJECT, "CD34"))

    assert silent_install.silent_refusal(
        _per_user_eligibility(), verified=True, signer="AB12") == ""


def test_a_signer_not_read_yet_waits(windows):
    assert silent_install.silent_refusal(
        _per_user_eligibility(), verified=True, signer="AB12") != ""


def test_the_download_reads_the_app_s_signer_for_the_quit(monkeypatch, tmp_path):
    """The quit's gate runs on the main thread: the download thread has
    already read this app's signer by the time the update is ready."""
    path = tmp_path / "Mixar-3.4.0.msi"
    path.write_bytes(b"x")
    monkeypatch.setattr(install_flow.os, "name", "nt")
    monkeypatch.setattr(install_flow, "_prepare_staging", lambda *_a: str(path))
    monkeypatch.setattr(install_flow, "_already_staged", lambda *_a: True)
    monkeypatch.setattr(install_flow.verify, "verify_installer",
                        lambda *_a, **_kw: (verify.VERIFIED, SUBJECT, "AB12"))
    monkeypatch.setattr(install_flow, "_on_main_thread", lambda _fn: None)
    monkeypatch.setattr(install_flow, "get_update_state", lambda: SimpleNamespace(
        set_download_progress=lambda *_a: None, set_ready=lambda *_a: None))
    monkeypatch.setattr(staged_record, "write_ready", lambda *_a, **_kw: None)
    calls = []
    monkeypatch.setattr(verify, "_authenticode",
                        lambda p: calls.append(p) or ("Valid", SUBJECT, "CD34"))
    info = SimpleNamespace(latest_version="3.4.0", download_url="u", download_sha256="s",
                           installer_type="msi")

    install_flow._worker(info, _per_user_eligibility(), EXE)

    assert calls == [EXE]
    assert win_signer.app_subject() == SUBJECT


# ---------------------------------------------------------------------------
# The helper's pin
# ---------------------------------------------------------------------------


@pytest.fixture
def launched(monkeypatch):
    monkeypatch.setattr(installer.os, "name", "nt")
    launch = MagicMock(return_value="proc")
    monkeypatch.setattr(win_installer, "launch", launch)
    return launch


def _begin(trigger, verified=True):
    return installer.begin_install(
        installer_path=r"C:\Users\qa\AppData\Local\Mixar\Updates\Mixar-3.4.0.msi",
        staging_dir=r"C:\Users\qa\AppData\Local\Mixar\Updates", version="3.4.0",
        eligibility=_per_user_eligibility(), verified=verified,
        signer_thumbprint="AB12", trigger=trigger, relaunch=trigger == TRIGGER_CLICK)


@pytest.mark.parametrize("trigger", [TRIGGER_QUIT, TRIGGER_LAUNCH])
def test_an_install_nobody_asked_for_pins_the_app_s_subject(launched, monkeypatch, trigger):
    _app_signed(monkeypatch, ("Valid", SUBJECT, "CD34"))

    assert _begin(trigger) == "proc"

    kwargs = launched.call_args.kwargs
    assert (kwargs["signer_thumbprint"], kwargs["signer_subject"]) == ("AB12", SUBJECT)
    assert kwargs["require_signature"] is True


@pytest.mark.parametrize("trigger", [TRIGGER_QUIT, TRIGGER_LAUNCH])
@pytest.mark.parametrize("answer", [("NotSigned", "", ""), None])
def test_an_unsigned_app_starts_no_helper_nobody_asked_for(launched, monkeypatch, trigger, answer):
    _app_signed(monkeypatch, answer)

    with pytest.raises(ValueError):
        _begin(trigger)
    with pytest.raises(ValueError):
        _begin(trigger, verified=False)
    launched.assert_not_called()


def test_an_unsigned_dev_build_still_updates_from_a_click(launched, monkeypatch):
    _app_signed(monkeypatch, ("NotSigned", "", ""))

    assert _begin(TRIGGER_CLICK) == "proc"
    assert launched.call_args.kwargs["signer_subject"] == ""


def test_a_signed_app_s_click_pins_its_subject_too(launched, monkeypatch):
    _app_signed(monkeypatch, ("Valid", SUBJECT, "CD34"))

    _begin(TRIGGER_CLICK)

    assert launched.call_args.kwargs["signer_subject"] == SUBJECT


def _environment(**overrides):
    arguments = dict(installer_path=r"C:\s\Mixar-3.4.0.msi", staging_dir=r"C:\s",
                     version="3.4.0", relaunch_candidates=[EXE])
    arguments.update(overrides)
    return win_installer.helper_environment(**arguments)


def test_the_subject_reaches_the_helper_through_its_environment():
    assert _environment(signer_subject=SUBJECT)["SIGNERSUBJECT"] == SUBJECT
    # Always set, so an inherited SIGNERSUBJECT is removed, never kept.
    assert _environment()["SIGNERSUBJECT"] == ""


def test_the_launched_helper_carries_the_subject_only_when_it_verifies(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(win_installer, "windows_system_dir", lambda: r"C:\Windows\System32")
    monkeypatch.setattr(win_installer.subprocess, "Popen",
                        lambda argv, **kw: seen.append(kw["env"]) or SimpleNamespace(pid=1))
    staging = str(tmp_path)
    for require in (True, False):
        win_installer.launch(
            installer_path=str(tmp_path / "Mixar-3.4.0.msi"), staging_dir=staging,
            version="3.4.0", relaunch_candidates=[EXE], require_signature=require,
            signer_thumbprint="AB12", signer_subject=SUBJECT, install_dir=INSTALL_DIR)

    assert seen[0].get("SIGNERSUBJECT") == SUBJECT
    assert "SIGNERSUBJECT" not in seen[1]


@pytest.mark.parametrize("name", ["_PS_VERIFY", "_PS_HELD_VERIFY"])
def test_both_helper_checks_require_the_subject_exactly(name):
    snippet = getattr(win_helper_ps, name)
    assert "$s.SignerCertificate.Subject -cne $env:SIGNERSUBJECT" in snippet
    assert "$env:SIGNERSUBJECT -and" in snippet  # an unsigned dev build's click


# ---------------------------------------------------------------------------
# The launch: the real request path, with nothing read before it
# ---------------------------------------------------------------------------


@pytest.fixture
def windows_launch(staged, monkeypatch):
    """A crashed session left a verified update staged and Windows starts
    Mixar: nothing has read this app's signer yet when the request is
    built, as at every real launch. Only the gate's ``os.name`` is Windows."""
    import os

    from mixar.modules.common.updates.core import launch_install

    nt = SimpleNamespace(name="nt", path=os.path)
    monkeypatch.setattr(silent_install, "os", nt)
    monkeypatch.setattr(launch_install, "os", nt)
    staged.answer = ("Valid", SUBJECT, "CD34")
    # Each read of this app's signer, with the launch's own verdict as it
    # stood then (None: not published yet).
    staged.reads = []

    def authenticode(path):
        staged.reads.append((path, launch_install._pending["check"]["verdict"]))
        return staged.answer

    monkeypatch.setattr(verify, "_authenticode", authenticode)
    return staged


def _start_windows_launch(staged):
    """The real bootstrap path: request, both checks, the announcement."""
    from mixar.bootstrap import update_checker as boot
    from mixar.modules.common.updates.core import launch_install

    assert win_signer.app_subject() == ""
    assert boot._launch_install_started() is True
    # The signature check is in; this launch's update check is not.
    assert launch_install._await_verdict() == launch_install._VERIFY_POLL_S
    assert launch_install._check_offer() is None
    assert launch_install._await_verdict() is None  # both in: announced
    return launch_install


def test_a_windows_launch_installs_once_its_own_check_read_the_app_s_signer(windows_launch):
    launch_install = _start_windows_launch(windows_launch)
    # Read by the launch's own signature check, before its verdict was
    # published, so before the gate below could look.
    assert windows_launch.reads == [(windows_launch.bpy.app.binary_path, None)]
    assert win_signer.app_subject() == SUBJECT

    launch_install._install()

    windows_launch.begin.assert_called_once()
    assert windows_launch.begin.call_args.kwargs["trigger"] == TRIGGER_LAUNCH


def test_an_unsigned_windows_app_stands_down_at_the_launch_gate(windows_launch):
    windows_launch.answer = ("NotSigned", "", "")
    launch_install = _start_windows_launch(windows_launch)

    launch_install._install()

    windows_launch.begin.assert_not_called()
    record = staged_record.read(str(windows_launch.directory))
    assert record["launch_attempts"] == 0  # refused before the attempt counts
