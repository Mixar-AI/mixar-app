# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Launch/stop one isolated real-app MCP QA fixture without touching user settings.

First prepare tests/mcp/e2e_backend.py in the backend repo. The fixture contains
temporary credentials for its new loopback-only database; none are printed.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time
from urllib.parse import urlsplit


def fingerprint(pid):
    return subprocess.run(["ps", "-p", str(pid), "-o", "lstart=", "-o", "command="],
                          capture_output=True, text=True, check=False).stdout.strip()


def stop(directory):
    marker = directory / "app-process.json"
    if not marker.exists():
        raise RuntimeError("No owned QA app marker exists")
    record = json.loads(marker.read_text())
    current = fingerprint(record["pid"])
    if current and current != record["fingerprint"]:
        raise RuntimeError("PID was reused; refusing to stop another process")
    if current:
        try:
            with socket.create_connection(("127.0.0.1", record["qa_port"]), timeout=5) as connection:
                connection.sendall(b'{"cmd":"quit","args":{}}\n')
        except OSError:
            pass
        for _ in range(50):
            if not fingerprint(record["pid"]):
                break
            time.sleep(0.1)
        if fingerprint(record["pid"]) == current:
            os.kill(record["pid"], signal.SIGTERM)
    marker.unlink()
    print("Stopped this fixture's QA app")


def launch(options):
    directory = options.fixture.resolve()
    fixture = json.loads((directory / "fixture.json").read_text())
    target = urlsplit(fixture["backend_url"])
    if target.scheme != "http" or target.hostname not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("QA fixture must use a loopback backend")
    profile = directory / "profile"
    if profile.exists() or (directory / "app-process.json").exists():
        raise RuntimeError("Use a fresh fixture directory; this profile already exists")
    app, harness = options.app.resolve(), options.qa_harness.resolve()
    if not app.is_file() or not (harness / "qa_boot_startup.py").is_file():
        raise RuntimeError("Pass the built app executable and installed QA harness directory")
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", options.qa_port)) == 0:
            raise RuntimeError("QA port already belongs to a running process")
    for part in ("scripts/startup", "datafiles/mixar", "config/mixar"):
        (profile / part).mkdir(parents=True, exist_ok=True)
    shutil.copy(harness / "qa_boot_startup.py", profile / "scripts/startup/qa_boot.py")
    (profile / "datafiles/mixar/onboarding_seen.json").write_text(
        json.dumps({"users_seen": [fixture["username"]]}))
    config = profile / "config/mixar/mixar.json"
    config.write_text(json.dumps({
        "backend_url": fixture["backend_url"], "share_usage_data": False,
        "dev_bypass": {"enabled": True, "username": fixture["username"], "password": fixture["password"]},
        "mcp_enabled": False, "ui_mode": "ai",
    }))
    config.chmod(0o600)
    marker = {"app": str(app), "harness": str(harness), "qa_port": options.qa_port,
              "normal_input": bool(options.normal_input)}
    pid = start(directory, marker, mode="w")
    print(json.dumps({"pid": pid, "profile": str(profile),
                      "qa_port": options.qa_port, "backend_url": fixture["backend_url"]}))


def start(directory, marker, blend=None, mode="a"):
    """Start the app on the fixture's profile; the environment (for example a
    temporary CLAUDE_CONFIG_DIR or CODEX_HOME) is inherited."""
    env = dict(os.environ, MIXAR_QA="1", MIXAR_USER_RESOURCES=str(directory / "profile"),
               MIXAR_QA_OUT=str(directory), MIXAR_QA_PORT=str(marker["qa_port"]),
               MIXAR_MCP_DISCOVERY_DIR=str(directory / "discovery"),
               MIXAR_OPERATION_HISTORY_DIR=str(directory / "ophistory"))
    with (directory / "app.log").open(mode) as log:
        process = subprocess.Popen([
            marker["app"], "-p", "60", "60", "1680", "1050", *([str(blend)] if blend else []),
            *([] if marker["normal_input"] else ["--enable-event-simulate"]),
            "--python", str(Path(marker["harness"]) / "driver/qa_server.py"),
        ], env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    (directory / "app-process.json").write_text(json.dumps(
        {**marker, "pid": process.pid, "fingerprint": fingerprint(process.pid)}))
    return process.pid


def relaunch(directory, blend=None):
    """Quit this fixture's app and start it again on the SAME profile, as a user
    reopening Mixar (optionally on a saved file). A new process is a new instance."""
    marker = json.loads((directory / "app-process.json").read_text())
    stop(directory)
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", marker["qa_port"])) == 0:
            raise RuntimeError("QA port still belongs to a running process")
    pid = start(directory, {key: marker[key] for key in ("app", "harness", "qa_port", "normal_input")}, blend)
    print(json.dumps({"pid": pid, "file": str(blend) if blend else None}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--app", type=Path)
    parser.add_argument("--qa-harness", type=Path)
    parser.add_argument("--qa-port", type=int, default=4797)
    parser.add_argument("--normal-input", action="store_true", help="Test production native input without QA event simulation")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--relaunch", nargs="?", const="", metavar="FILE",
                        help="Restart this fixture's app on its profile, optionally opening FILE")
    options = parser.parse_args()
    if options.stop:
        stop(options.fixture)
    elif options.relaunch is not None:
        relaunch(options.fixture.resolve(), Path(options.relaunch).resolve() if options.relaunch else None)
    elif not options.app or not options.qa_harness:
        parser.error("--app and --qa-harness are required for launch")
    elif not 1 <= options.qa_port <= 65535:
        parser.error("--qa-port must be between 1 and 65535")
    else:
        launch(options)


if __name__ == "__main__":
    main()
