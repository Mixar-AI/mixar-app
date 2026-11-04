# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""MIN_BACKEND_VERSION travels from the repo root to the backend's release
row: orchestrator → manifest → publish → push_release --requires-backend.
A backend below it never offers the release (the offer gate), which is what
lets client and backend be merged and published in any order."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def test_min_backend_version_file_is_semver():
    assert SEMVER.match((ROOT / "MIN_BACKEND_VERSION").read_text().strip())


def test_orchestrator_reads_the_file_into_the_manifest():
    wf = (ROOT / ".github/workflows/release-orchestrator.yml").read_text()
    assert "MIN_BACKEND_VERSION" in wf
    assert "requires_backend=$REQUIRES_BACKEND" in wf
    assert "REQUIRES_BACKEND: ${{ needs.prepare.outputs.requires_backend }}" in wf
    builder = (ROOT / ".github/scripts/build_release_manifest.py").read_text()
    assert '"requires_backend": os.environ.get("REQUIRES_BACKEND"' in builder


def test_publish_passes_it_and_dispatches_the_backend_promote():
    wf = (ROOT / ".github/workflows/publish-release.yml").read_text()
    assert "--requires-backend" in wf
    assert "promote-ecs.yml" in wf and "repositories: mixar-backend" in wf
    push = (ROOT / "scripts/ci/push_release.py").read_text()
    assert '"--requires-backend"' in push
    assert "/updates/releases/{version}/notify" in push
    assert "/notifications/send" not in push


def test_manifest_loader_emits_requires_backend(tmp_path):
    manifest = {
        "schema_version": 1, "status": "pending", "version": "4.5.0", "tag": "v4.5.0",
        "channel": "stable", "severity": "recommended", "notify": True,
        "min_supported_version": None, "force_update_below": None,
        "requires_backend": "3.4.0",
        "release_notes_md": "Notes", "technical_notes_md": "Tech", "internal_notes_md": "",
        "platforms": {
            "mac": {"s3_key": "releases/4.5.0/m.dmg", "size": 1, "sha256": "a" * 64},
            "windows": {"s3_key": "releases/4.5.0/w.msi", "size": 1, "sha256": "b" * 64},
        },
    }
    mf = tmp_path / "manifest.json"
    mf.write_text(json.dumps(manifest))
    out = tmp_path / "out.txt"
    env = {**os.environ, "VERSION": "4.5.0", "MANIFEST_FILE": str(mf), "GITHUB_OUTPUT": str(out)}
    res = subprocess.run([sys.executable, "-I", str(ROOT / ".github/scripts/load_release_manifest.py")],
                         env=env, capture_output=True, text=True, cwd=tmp_path)
    assert res.returncode == 0, res.stderr + res.stdout
    assert "requires_backend=3.4.0" in out.read_text()
