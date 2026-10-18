# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Godot discovery (fork marker) and the headless runner (contract §3),
driven against a fake ``mixar-godot`` Python script."""

import json
import os
import threading

from mixar.modules.game_studio.core import godot_locator, godot_runner


def _touch_exe(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write("#!/bin/sh\n")
    os.chmod(path, 0o755)
    return path


def test_candidates_follow_contract_order_on_macos(tmp_path):
    home = str(tmp_path / "home")
    user_app = _touch_exe(os.path.join(home, "Applications", "Mixar Godot.app", "Contents", "MacOS", "Mixar Godot"))
    dev = _touch_exe(os.path.join(home, "Work", "Mixar", "mixar-godot", "bin", "godot.macos.editor.arm64"))
    _touch_exe(os.path.join(home, "Work", "Mixar", "mixar-godot", "bin", "godot.macos.editor.arm64.dSYM"))
    found = godot_locator.candidates("/cfg/godot", {"MIXAR_GODOT_BIN": "/env/godot"},
                                     home=home, platform="darwin")
    sources = [source for source, _ in found]
    paths = [path for _, path in found]
    assert sources[:2] == ["config", "env"] and paths[:2] == ["/cfg/godot", "/env/godot"]
    assert paths.index(user_app) < paths.index(dev)
    assert not any(p.endswith(".dSYM") for p in paths)


def test_candidates_windows_localappdata(tmp_path):
    local = str(tmp_path / "Local")
    exe = _touch_exe(os.path.join(local, "Mixar", "godot", "mixar-godot-1.0.exe"))
    found = godot_locator.candidates("", {"LOCALAPPDATA": local}, home=str(tmp_path), platform="win32")
    assert found == [("app", exe)]


def test_validate_accepts_fork_and_caches(fake_godot):
    calls = []
    real = __import__("subprocess").run

    def counting(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    verdict = godot_locator.validate(fake_godot, runner=counting)
    assert verdict["found"] and verdict["version"] == "1.0.0" and verdict["godot"] == "4.7.2.stable"
    godot_locator.validate(fake_godot, runner=counting)
    assert len(calls) == 1


def test_validate_refuses_stock_godot(fake_godot, monkeypatch):
    monkeypatch.setenv("FAKE_FORK", "")
    verdict = godot_locator.validate(fake_godot)
    assert not verdict["found"] and verdict["error"] == "not_mixar_fork"
    assert "stock Godot" in verdict["message"]


def test_locate_skips_refusals_and_reports_best_reason(fake_godot, tmp_path, monkeypatch):
    missing = str(tmp_path / "nope")
    verdict = godot_locator.locate(missing, {"MIXAR_GODOT_BIN": fake_godot}, home=str(tmp_path),
                                   platform="darwin")
    assert verdict["found"] and verdict["source"] == "env"
    godot_locator.forget()
    monkeypatch.setenv("FAKE_FORK", "stock")
    verdict = godot_locator.locate(missing, {"MIXAR_GODOT_BIN": fake_godot}, home=str(tmp_path),
                                   platform="darwin")
    assert verdict["error"] == "not_mixar_fork"  # more telling than the missing config path
    assert godot_locator.cached_status()["error"] == "not_mixar_fork"


def test_parse_progress_and_version_output():
    assert godot_runner.parse_progress('MIXAR_PROGRESS {"step":"import","pct":40,"message":"x"}') == \
        {"step": "import", "pct": 40.0, "message": "x"}
    assert godot_runner.parse_progress('MIXAR_PROGRESS {"pct": 400}')["pct"] == 100.0
    assert godot_runner.parse_progress("MIXAR_PROGRESS nope") is None
    assert godot_runner.parse_progress("Godot Engine v4.7") is None
    out = 'banner\n{"fork":"mixar-godot","fork_version":"1.0.0"}\n'
    assert godot_locator.parse_version_output(out)["fork"] == "mixar-godot"


def test_run_build_streams_progress_and_reads_result(fake_godot, write_spec, tmp_path):
    game = str(tmp_path / "game")
    export = write_spec(game)
    seen = []
    result = godot_runner.run(
        fake_godot, ["--headless", "--mixar-build", os.path.join(export, "game_spec.json"),
                     "--mixar-out", os.path.join(game, "project")],
        str(tmp_path / "build.json"), "build", on_progress=lambda *a: seen.append(a))
    assert result["ok"] and result["stats"]["nodes"] == 1
    assert [pct for pct, _step, _msg in seen] == [10.0, 60.0, 100.0]
    assert os.path.isfile(os.path.join(game, "project", "project.godot"))


def test_run_without_result_file_maps_exit_code(fake_godot, tmp_path, monkeypatch):
    stale = tmp_path / "r.json"
    stale.write_text(json.dumps({"schema": "mixar_godot_result_v1", "ok": True}))
    monkeypatch.setenv("FAKE_FAIL_CODE", "4")
    result = godot_runner.run(fake_godot, ["--mixar-export", "web"], str(stale), "export")
    assert not result["ok"] and result["error_code"] == "templates_missing"
    assert "something broke" in result["error"]  # last output line, not the stale file


def test_run_cancel_stops_the_process(fake_godot, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SLEEP", "30")
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    result = godot_runner.run(fake_godot, ["--mixar-build", "x", "--mixar-out", str(tmp_path)],
                              str(tmp_path / "r.json"), "build", cancel=cancel)
    assert result["error_code"] == "cancelled"


def test_run_launch_failure_is_reported(tmp_path):
    result = godot_runner.run(str(tmp_path / "missing"), [], str(tmp_path / "r.json"), "build")
    assert result["error_code"] == "launch_failed"
