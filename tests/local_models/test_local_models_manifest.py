# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Manifest: atomic JSON persistence + once-only token minting."""

import json
import os

import pytest

from mixar.modules.local_models.core import manifest, paths


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "_resolved_base", str(tmp_path))
    yield tmp_path


def test_defaults_when_no_file():
    data = manifest.load()
    assert data["runtime"] == {"tag": None, "variant_asset": None, "ready": False}
    assert data["models"] == {}
    assert data["active_model_id"] is None
    assert data["port"] is None
    assert data["registered"] is None


def test_api_token_minted_exactly_once(store):
    first = manifest.get_api_token()
    second = manifest.get_api_token()
    assert first == second
    assert len(first) >= 24
    on_disk = json.loads((store / "manifest.json").read_text())
    assert on_disk["api_token"] == first


def test_atomic_write_leaves_no_temp_files(store):
    manifest.set_runtime("b10485", "llama-b10485-bin-macos-arm64.tar.gz", True)
    manifest.set_port(11500)
    leftovers = [name for name in os.listdir(store) if name.endswith(".tmp")]
    assert leftovers == []
    on_disk = json.loads((store / "manifest.json").read_text())
    assert on_disk["runtime"]["ready"] is True
    assert on_disk["port"] == 11500


def test_runtime_roundtrip():
    manifest.set_runtime("b10485", "llama-b10485-bin-win-vulkan-x64.zip", True)
    runtime = manifest.get_runtime()
    assert runtime == {
        "tag": "b10485",
        "variant_asset": "llama-b10485-bin-win-vulkan-x64.zip",
        "ready": True,
    }


def test_model_ready_flags():
    assert manifest.ready_model_ids() == ()
    manifest.set_model_files_ready("qwen3.5-4b", True)
    manifest.set_model_files_ready("qwen3.5-2b", False)
    assert manifest.ready_model_ids() == ("qwen3.5-4b",)
    assert manifest.get_model_state("qwen3.5-4b") == {"files_ready": True}
    assert manifest.get_model_state("missing") == {}


def test_active_model_and_port_roundtrip():
    manifest.set_active_model_id("qwen3.5-9b")
    manifest.set_port(11507)
    assert manifest.get_active_model_id() == "qwen3.5-9b"
    assert manifest.get_port() == 11507


def test_registered_snapshot_roundtrip():
    manifest.set_registered("http://127.0.0.1:11500", "qwen3.5-4b", True)
    assert manifest.get_registered() == {
        "base_url": "http://127.0.0.1:11500",
        "model_id": "qwen3.5-4b",
        "supports_vision": True,
    }
    manifest.set_registered(None, None, None)
    assert manifest.get_registered() is None


def test_corrupt_manifest_recovers_to_defaults(store):
    (store / "manifest.json").write_text("{not json")
    data = manifest.load()
    assert data["models"] == {}
    # A token mint rewrites a valid file over the corrupt one.
    token = manifest.get_api_token()
    on_disk = json.loads((store / "manifest.json").read_text())
    assert on_disk["api_token"] == token
