# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mixar Library (contract v1.1): safe extraction, sha256-verified install,
self-test, platform selection, uninstall/prune and launch gating.

Runs on macOS/Linux: the Windows paths (``.exe`` entry points, Windows
LOCALAPPDATA) are exercised with fakes only — nothing here executes a
Windows program."""

import hashlib
import io
import json
import os
import plistlib
import stat
import sys
import threading
import zipfile

import pytest

from mixar.modules.game_studio.core import agent_api, approvals, jobs, library, library_install
from mixar.modules.game_studio.core import safe_extract
from mixar.modules.game_studio.core.store_client import StoreClient, StoreError

from test_game_studio_store_client import _envelope, stub  # noqa: F401 — fixture

SELFTEST_SCRIPT = (f"#!{sys.executable}\n"
                   "import json, sys\n"
                   "if '--mixar-selftest' in sys.argv:\n"
                   "    ok = '--headless' in sys.argv\n"
                   "    print('MIXAR_SELFTEST ' + json.dumps({'ok': ok, 'collected': 1}))\n"
                   "    sys.exit(0 if ok else 1)\n")


@pytest.fixture(autouse=True)
def _clean_library():
    library.reset_for_tests()
    approvals.reset_for_tests()
    yield
    library.reset_for_tests()
    approvals.reset_for_tests()


class Handle:
    def __init__(self):
        self.cancel_event = threading.Event()
        self.steps = []

    def progress(self, pct, message=None, force=False):
        self.steps.append((pct, message))


def _zip(entries, modes=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in entries.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (modes or {}).get(name, 0o100644) << 16
            archive.writestr(info, body)
    return buffer.getvalue()


def _mac_app(script=SELFTEST_SCRIPT):
    plist = plistlib.dumps({"CFBundleExecutable": "Crystal Run"})
    # No exec bit in the zip: the installer must chmod the program itself.
    return _zip({"Crystal Run.app/Contents/Info.plist": plist,
                 "Crystal Run.app/Contents/MacOS/Crystal Run": script})


# --- safe extraction -------------------------------------------------------------

@pytest.mark.parametrize("name", ["../evil.txt", "a/../../evil.txt", "/etc/evil", "C:/evil.txt",
                                  "a\\..\\evil.txt"])
def test_zip_slip_and_absolute_paths_are_refused(tmp_path, name):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("ok.txt", "fine")
        handle.writestr(zipfile.ZipInfo(name), "evil")
    with pytest.raises(safe_extract.UnsafeArchive):
        safe_extract.extract(str(archive), str(tmp_path / "out"))
    assert not (tmp_path / "out").exists() and not (tmp_path / "evil.txt").exists()


def test_symlinks_and_duplicates_are_refused(tmp_path):
    link = tmp_path / "link.zip"
    link.write_bytes(_zip({"game/data": "/etc/passwd"}, {"game/data": stat.S_IFLNK | 0o777}))
    with pytest.raises(safe_extract.UnsafeArchive, match="symlink"):
        safe_extract.extract(str(link), str(tmp_path / "a"))
    dup = tmp_path / "dup.zip"
    with zipfile.ZipFile(dup, "w") as handle:
        handle.writestr("Game.exe", "1")
        handle.writestr("game.EXE", "2")  # same file on case-insensitive volumes
    with pytest.raises(safe_extract.UnsafeArchive, match="twice"):
        safe_extract.extract(str(dup), str(tmp_path / "b"))
    assert not (tmp_path / "a").exists() and not (tmp_path / "b").exists()


def test_good_archive_extracts_with_safe_modes(tmp_path):
    archive = tmp_path / "good.zip"
    archive.write_bytes(_zip({"Game/run": "#!/bin/sh\n", "Game/data.pck": "x"},
                             {"Game/run": 0o104755, "Game/data.pck": 0o100666}))
    assert safe_extract.extract(str(archive), str(tmp_path / "out")) == 2
    assert stat.S_IMODE(os.stat(tmp_path / "out/Game/run").st_mode) == 0o755  # setuid dropped
    assert stat.S_IMODE(os.stat(tmp_path / "out/Game/data.pck").st_mode) == 0o644
    with pytest.raises(safe_extract.UnsafeArchive):
        safe_extract.inside(str(tmp_path / "out"), "../outside")


# --- listing ---------------------------------------------------------------------

def test_normalize_listing_shapes_and_host_platform():
    builds = [{"build_id": "bm", "platform": "macos", "version": "1", "sha256": "AB", "size_bytes": 3,
               "launch": "Crystal Run.app"}, {"build_id": "bw", "platform": "windows"}]
    nested = {"items": [{"game": {"game_id": "g1", "slug": "crystal-run", "title": "Crystal Run"},
                         "builds": builds}]}
    flat = [{"id": "g1", "slug": "crystal-run", "builds": {"macos": builds[0]}}]
    for data in (nested, flat):
        game = library.normalize_listing(data)[0]
        assert game["game_id"] == "g1" and game["builds"]["macos"]["sha256"] == "ab"
    assert set(library.normalize_listing(nested)[0]["builds"]) == {"macos", "windows"}
    assert library.normalize_listing({"items": [{"title": "no id"}]}) == []
    assert [library.host_platform(p) for p in ("darwin", "win32", "linux")] == ["macos", "windows", "linux"]


# --- install / self-test / uninstall ---------------------------------------------

def _serve_game(stub, payload, platform="macos", record_sha=None, served_sha=None):  # noqa: F811
    digest = hashlib.sha256(payload).hexdigest()
    build = {"build_id": "b2", "platform": platform, "version": "1.1", "sha256": record_sha or digest,
             "size_bytes": len(payload),
             "launch": "Crystal Run.app" if platform == "macos" else "Crystal Run.exe"}
    stub.routes.update({
        ("GET", "/api/v1/me/library"): (200, _envelope({"items": [
            {"game": {"game_id": "g1", "slug": "crystal-run", "title": "Crystal Run"},
             "builds": [build]}]})),
        ("GET", "/api/v1/games/g1/builds/b2/download"): (200, _envelope({
            "url": stub.base + "/files/b2.zip", "sha256": served_sha or build["sha256"],
            "size_bytes": len(payload), "launch": build["launch"], "platform": platform,
            "version": "1.1"})),
        ("GET", "/files/b2.zip"): (200, payload),
    })


def _client(stub):  # noqa: F811
    return lambda base: StoreClient(stub.base, token_provider=lambda: "tok")


def _install(stub, root, platform="macos", run_selftest=True):  # noqa: F811
    work = library_install.install_by_slug_work(str(root), stub.base, "crystal-run", platform,
                                                _client(stub), run_selftest=run_selftest)
    return work(Handle())


@pytest.mark.skipif(sys.platform.startswith("win"), reason="runs the fake macOS program")
def test_install_verifies_extracts_selftests_and_updates(stub, tmp_path):  # noqa: F811
    root = tmp_path / "library"
    root.mkdir()
    (root / "crystal-run" / "b1").mkdir(parents=True)  # an older build
    library.save_index(str(root), {"crystal-run": {"build_id": "b1", "launch": "x", "platform": "macos"}})
    _serve_game(stub, _mac_app())
    result = _install(stub, root)
    assert result["build_id"] == "b2" and result["selftest"]["ok"], result
    program = root / "crystal-run/b2/Crystal Run.app/Contents/MacOS/Crystal Run"
    assert os.access(program, os.X_OK)
    assert not (root / "crystal-run/b1").exists() and not (root / ".downloads").exists()
    index = json.loads((root / "installed.json").read_text())
    assert index["crystal-run"]["build_id"] == "b2" and index["crystal-run"]["selftest"]["ok"]
    download = next(c for c in stub.calls if c["path"] == "/files/b2.zip")
    assert "Authorization" not in download["headers"]  # signed URL, no bearer
    listing = agent_api.library_list()
    assert listing["games"][0]["installed"]["selftest"] == "passed"
    assert not listing["games"][0]["update_available"]


def test_sha_mismatch_installs_nothing(stub, tmp_path):  # noqa: F811
    root = tmp_path / "library"
    root.mkdir()
    _serve_game(stub, _mac_app(), record_sha="0" * 64)
    with pytest.raises(jobs.JobError) as caught:
        _install(stub, root)
    assert caught.value.code == "sha256_mismatch"
    assert not (root / "crystal-run" / "b2").exists() and not list((root / ".downloads").iterdir())
    _serve_game(stub, _mac_app(), served_sha="1" * 64)  # download endpoint disagrees with library
    with pytest.raises(jobs.JobError) as caught:
        _install(stub, root)
    assert caught.value.code == "sha256_mismatch"


def test_fetch_checks_size_and_sha(stub, tmp_path):  # noqa: F811
    stub.routes[("GET", "/files/x.zip")] = (200, b"abc")
    client = StoreClient(stub.base, token_provider=lambda: "tok")
    target = tmp_path / "x.zip"
    with pytest.raises(StoreError, match="size") as caught:
        client.fetch(stub.base + "/files/x.zip", str(target), hashlib.sha256(b"abc").hexdigest(), 99)
    assert caught.value.code == "size_mismatch" and not target.exists()
    assert client.fetch(stub.base + "/files/x.zip", str(target), hashlib.sha256(b"abc").hexdigest(), 3)


def test_unsafe_build_is_refused_and_selftest_failure_reported(stub, tmp_path):  # noqa: F811
    root = tmp_path / "library"
    root.mkdir()
    _serve_game(stub, _zip({"../escape": "x"}))
    with pytest.raises(jobs.JobError) as caught:
        _install(stub, root)
    assert caught.value.code == "unsafe_archive" and not (tmp_path / "escape").exists()
    failing = SELFTEST_SCRIPT.replace("ok = '--headless' in sys.argv", "ok = False")
    _serve_game(stub, _mac_app(failing))
    result = _install(stub, root)
    assert result["selftest"]["ok"] is False and result["selftest"]["exit_code"] == 1


def test_windows_entry_point_and_launch_with_fakes(tmp_path):
    """Windows only by fakes: no .exe is executed here."""
    install = tmp_path / "library" / "crystal-run" / "bw"
    install.mkdir(parents=True)
    (install / "Crystal Run.exe").write_bytes(b"MZ")
    assert library_install.executable_for(str(install), "Crystal Run.exe", "windows").endswith("Crystal Run.exe")
    with pytest.raises(safe_extract.UnsafeArchive):
        library_install.executable_for(str(install), "..\\..\\cmd.exe", "windows")
    library.save_index(str(tmp_path / "library"), {"crystal-run": {
        "build_id": "bw", "launch": "Crystal Run.exe", "platform": "windows", "title": "Crystal Run"}})
    started = []
    reply = library_install.launch_installed(str(tmp_path / "library"), "crystal-run",
                                             popen=lambda cmd, **kw: started.append(cmd),
                                             runner=lambda cmd, **kw: _Done())
    assert reply["ok"] and started[0][0].endswith("Crystal Run.exe") and started[0][1:] == []
    selftest_cmd = []
    library_install.selftest("C:/game/Crystal Run.exe", "C:/game",
                             runner=lambda cmd, **kw: selftest_cmd.append(cmd) or _Done())
    assert selftest_cmd[0][1:] == ["--headless", "--", "--mixar-selftest"]


class _Done:
    returncode = 0
    stdout = 'noise\nMIXAR_SELFTEST {"ok": true}\n'


def test_uninstall_and_prune(tmp_path):
    root = tmp_path / "library"
    (root / "crystal-run" / "b2").mkdir(parents=True)
    (root / "stale-game" / "b9").mkdir(parents=True)
    (root / ".downloads").mkdir()
    (root / "crystal-run" / "b3.staging").mkdir()
    library.save_index(str(root), {"crystal-run": {"build_id": "b2"}})
    removed = library.prune(str(root))
    assert sorted(os.listdir(root)) == ["crystal-run", "installed.json"]
    assert os.listdir(root / "crystal-run") == ["b2"] and ".downloads" in removed
    assert library_install.uninstall_work(str(root), "crystal-run")(Handle())["uninstalled"]
    assert not (root / "crystal-run").exists() and json.loads((root / "installed.json").read_text()) == {}


# --- launch gating ------------------------------------------------------------------

def test_agent_launch_needs_the_user(monkeypatch):
    from types import SimpleNamespace as NS
    monkeypatch.setattr(agent_api, "bpy", NS(app=NS(background=True)))
    assert agent_api.launch_library_game("crystal-run")["error_code"] == "approval_required_ui"
    monkeypatch.setattr(agent_api, "bpy", NS(app=NS(background=False)))
    assert agent_api.launch_library_game("crystal-run")["error_code"] == "not_installed"
    library._state["index"] = {"crystal-run": {"build_id": "b2", "title": "Crystal Run", "version": "1.1"}}
    monkeypatch.setattr(agent_api, "_ask_user_launch", lambda *a: None)
    reply = agent_api.launch_library_game("crystal-run")
    assert reply["state"] == "awaiting_user_approval"
    assert agent_api.game_job_status(reply["job_id"])["kind"] == "launch"
    token = approvals._issue_token(reply["request_id"])
    assert approvals._claim(reply["request_id"], token, kind="publish") is None  # kinds can't cross
    assert approvals._claim(reply["request_id"], token, kind="launch") == {"slug": "crystal-run"}


def test_launch_operators_are_user_only():
    from pathlib import Path
    from mixar.modules.space_mixie_chat.core.sandbox_denylist import op_denial_reason
    from mixar.modules.space_mixie_chat.core.sandbox_modules import is_denied_module
    for op in ("game_library_launch", "game_library_launch_approve", "game_publish_approve",
               "game_library_install"):
        assert op_denial_reason("mixar", op)
    assert op_denial_reason("mixar", "game_library_install")  # the user's install self-tests
    assert op_denial_reason("mixar", "game_library_refresh") is None
    for name in ("library", "library_install", "safe_extract"):
        assert is_denied_module(f"mixar.modules.game_studio.core.{name}")
    source = (Path(__file__).parents[2] / "src/scripts/mixar/modules/game_studio/ui/operators/"
              "game_library_ops.py").read_text(encoding="utf-8")
    for body in source.split("    def execute(self, context):")[1:]:
        if "_launch(self" in body.split("\n\n\n")[0]:
            assert "_refuse_agents(self)" in body.split("_launch(self")[0]
    assert "options={'HIDDEN', 'SKIP_SAVE'}" in source


def test_quarantine_is_never_stripped():
    from pathlib import Path
    root = Path(__file__).parents[2] / "src/scripts/mixar/modules/game_studio"
    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
        assert "xattr" not in code.replace("``com.apple.quarantine`` xattr", "") or path.name == "safe_extract.py", path
        assert "removexattr" not in code and '"-d"' not in code and "Zone.Identifier" not in code, path


# --- agents install but never execute ---------------------------------------------

@pytest.mark.skipif(sys.platform.startswith("win"), reason="builds a fake macOS program")
def test_agent_install_never_runs_the_program(stub, tmp_path, monkeypatch):  # noqa: F811
    def forbidden(*args, **kwargs):
        raise AssertionError("the downloaded program was executed")

    monkeypatch.setattr(library_install, "selftest", forbidden)
    root = tmp_path / "library"
    root.mkdir()
    _serve_game(stub, _mac_app())
    result = _install(stub, root, run_selftest=False)
    assert result["selftest"] is None
    assert json.loads((root / "installed.json").read_text())["crystal-run"]["selftest"] is None
    assert agent_api.library_list()["games"][0]["installed"]["selftest"] == "not_run"


def test_agent_api_install_requests_no_selftest(monkeypatch):
    captured = {}

    def fake_work(*args, **kwargs):
        captured.update(kwargs)
        return lambda handle: {}

    monkeypatch.setattr(library_install, "install_by_slug_work", fake_work)
    monkeypatch.setattr(library, "library_root", lambda: "/tmp/library")
    import mixar.config.config as config
    monkeypatch.setattr(config, "get_community_api_url", lambda: "http://store.test")
    assert agent_api.start_library_install("crystal-run")["ok"]
    assert captured == {"run_selftest": False}


def test_agent_api_has_no_route_to_run_a_download():
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).parents[2] / "src/scripts/mixar/modules/game_studio/core/"
                      "agent_api.py").read_text(encoding="utf-8"))
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | \
        {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & {"selftest", "launch_installed", "_claim", "_issue_token"}
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        for keyword in call.keywords:
            if keyword.arg == "run_selftest":
                assert isinstance(keyword.value, ast.Constant) and keyword.value.value is False


@pytest.mark.skipif(sys.platform.startswith("win"), reason="runs the fake macOS program")
def test_first_user_launch_selftests_and_refuses_a_failing_game(stub, tmp_path):  # noqa: F811
    root = tmp_path / "library"
    root.mkdir()
    failing = SELFTEST_SCRIPT.replace("ok = '--headless' in sys.argv", "ok = False")
    _serve_game(stub, _mac_app(failing))
    _install(stub, root, run_selftest=False)
    started = []
    reply = library_install.launch_installed(str(root), "crystal-run",
                                             popen=lambda cmd, **kw: started.append(cmd))
    assert reply["error_code"] == "selftest_failed" and not started
    index = json.loads((root / "installed.json").read_text())
    assert index["crystal-run"]["selftest"]["ok"] is False  # recorded, not re-run every Play
    _serve_game(stub, _mac_app())
    _install(stub, root, run_selftest=False)
    reply = library_install.launch_installed(str(root), "crystal-run",
                                             popen=lambda cmd, **kw: started.append(cmd))
    assert reply["ok"] and started and started[0][1:] == []


def test_free_game_is_acquired_before_install(stub, tmp_path):  # noqa: F811
    root = tmp_path / "library"
    root.mkdir()
    payload = _mac_app()
    _serve_game(stub, payload)
    listed = stub.routes[("GET", "/api/v1/me/library")]
    stub.routes[("GET", "/api/v1/me/library")] = (200, lambda raw: (
        listed if any(c["path"] == "/api/v1/games/g1/acquire" for c in stub.calls)
        else (200, _envelope({"items": []}))))
    stub.routes[("GET", "/api/v1/games/crystal-run")] = (200, _envelope({"game_id": "g1", "slug": "crystal-run"}))
    stub.routes[("POST", "/api/v1/games/g1/acquire")] = (200, _envelope({"acquired": True}))
    assert _install(stub, root, run_selftest=False)["build_id"] == "b2"
    paths = [c["path"] for c in stub.calls]
    assert paths.index("/api/v1/games/g1/acquire") < paths.index("/api/v1/games/g1/builds/b2/download")
