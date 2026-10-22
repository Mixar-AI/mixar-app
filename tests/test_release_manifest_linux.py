# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
SHA = "a" * 64


def _load(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_release_manifest_round_trips_linux_archive(tmp_path, monkeypatch):
    changelog = tmp_path / "changelog"
    changelog.mkdir()
    (changelog / "user.md").write_text("User notes\n", encoding="utf-8")
    (changelog / "technical.md").write_text("Technical notes\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"

    values = {
        "VERSION": "1.2.3",
        "TAG": "v1.2.3",
        "PR_NUMBER": "42",
        "MACOS_S3_KEY": "releases/1.2.3/mixar.dmg",
        "MACOS_SIZE_BYTES": "1",
        "MACOS_SHA256": SHA,
        "WINDOWS_S3_KEY": "releases/1.2.3/mixar.msi",
        "WINDOWS_SIZE_BYTES": "2",
        "WINDOWS_SHA256": SHA,
        "LINUX_S3_KEY": "releases/1.2.3/mixar.tar.xz",
        "LINUX_SIZE_BYTES": "3",
        "LINUX_SHA256": SHA,
        "CHANGELOG_DIR": str(changelog),
        "OUT_FILE": str(manifest_path),
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    _load("build_release_manifest", ".github/scripts/build_release_manifest.py").main()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["platforms"]["linux"] == {
        "s3_key": values["LINUX_S3_KEY"],
        "size": 3,
        "sha256": SHA,
        "installer_type": "tar.xz",
    }

    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("MANIFEST_FILE", str(manifest_path))
    monkeypatch.setenv("NOTES_DIR", str(tmp_path / "notes"))
    _load("load_release_manifest", ".github/scripts/load_release_manifest.py").main()
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert outputs["linux_s3_key"] == values["LINUX_S3_KEY"]
    assert outputs["linux_size"] == "3"
    assert outputs["linux_sha256"] == SHA
    assert outputs["has_linux"] == "true"


def test_loader_keeps_pre_linux_schema_v1_manifest_publishable(tmp_path, monkeypatch):
    manifest = {
        "schema_version": 1,
        "status": "pending",
        "version": "1.2.2",
        "tag": "v1.2.2",
        "channel": "stable",
        "severity": "recommended",
        "notify": True,
        "release_notes_md": "User notes",
        "technical_notes_md": "Technical notes",
        "platforms": {
            "mac": {"s3_key": "old/mixar.dmg", "size": 1, "sha256": SHA},
            "windows": {"s3_key": "old/mixar.msi", "size": 2, "sha256": SHA},
        },
    }
    manifest_path = tmp_path / "legacy.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    output = tmp_path / "github-output"
    monkeypatch.setenv("VERSION", "1.2.2")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("MANIFEST_FILE", str(manifest_path))
    monkeypatch.setenv("NOTES_DIR", str(tmp_path / "notes"))

    _load("load_legacy_release_manifest", ".github/scripts/load_release_manifest.py").main()

    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert outputs["has_linux"] == "false"
    assert outputs["linux_s3_key"] == ""
    assert outputs["linux_size"] == ""
    assert outputs["linux_sha256"] == ""
