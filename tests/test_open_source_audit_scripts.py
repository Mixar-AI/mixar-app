# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SPDX_LICENSE_TAG = "SPDX-License-" "Identifier:"


def run(cmd, cwd):
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def make_repo(path):
    run(["git", "init"], path)
    run(["git", "config", "user.email", "test@example.com"], path)
    run(["git", "config", "user.name", "Test User"], path)


def test_phase1_audit_scripts_generate_expected_reports(tmp_path):
    source_scripts = REPO_ROOT / "scripts" / "open_source"
    repo = tmp_path / "repo"
    repo.mkdir()
    make_repo(repo)

    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text(
        f"# {SPDX_LICENSE_TAG} GPL-3.0-or-later\nprint('hello')\n"
    )
    (repo / "src" / "token.txt").write_text("AWS_ACCESS_KEY_ID=AKIAEXAMPLE\n")
    (repo / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    run(["git", "add", "."], repo)
    run(["git", "commit", "-m", "initial"], repo)

    script = source_scripts / "run_phase1_audit.sh"
    result = run([str(script), "--output-dir", "audit-out"], repo)

    assert result.returncode == 0, result.stderr
    assert (repo / "audit-out" / "secret-audit" / "tracked-secret-patterns.txt").exists()
    assert (repo / "audit-out" / "secret-audit" / "history-sensitive-paths.txt").exists()
    assert (repo / "audit-out" / "license-asset-audit" / "tracked-assets.txt").exists()
    assert (repo / "audit-out" / "license-asset-audit" / "spdx-summary.txt").exists()

    secret_report = (repo / "audit-out" / "secret-audit" / "tracked-secret-patterns.txt").read_text()
    asset_report = (repo / "audit-out" / "license-asset-audit" / "tracked-assets.txt").read_text()
    spdx_report = (repo / "audit-out" / "license-asset-audit" / "spdx-summary.txt").read_text()

    assert "src/token.txt" in secret_report
    assert "image.png" in asset_report
    assert "GPL-3.0-or-later" in spdx_report
