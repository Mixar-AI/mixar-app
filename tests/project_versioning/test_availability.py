# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

import importlib.util

from mixar.modules.project_versioning.core.availability import detect
from mixar.modules.project_versioning.core.models import Availability
from scripts.generate_config import generate_config


def test_build_flag_defaults_off_and_can_be_explicitly_enabled(monkeypatch, tmp_path) -> None:
    version_file = tmp_path / "VERSION"
    version_file.write_text("1.2.3")
    monkeypatch.delenv("MIXAR_LORE_PILOT_ENABLED", raising=False)
    assert generate_config(str(version_file))["lore_pilot"]["enabled"] is False
    monkeypatch.setenv("MIXAR_LORE_PILOT_ENABLED", "true")
    assert generate_config(str(version_file))["lore_pilot"]["enabled"] is True


def test_build_flag_fails_closed_without_probing_sdk(monkeypatch) -> None:
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name: (_ for _ in ()).throw(AssertionError("must not probe")),
    )
    assert detect(build_enabled=False) == Availability.BUILD_DISABLED


def test_missing_sdk_is_nonfatal_on_supported_platform(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("platform.machine", lambda: "arm64")
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert detect(build_enabled=True) == Availability.SDK_MISSING
