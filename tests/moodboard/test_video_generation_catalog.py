# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Video generation limits are projected from the backend catalog seed."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
import sys


MODULE_PATH = (
    Path(__file__).parents[2]
    / "src/scripts/mixar/modules/moodboard/core/video_generation_catalog.py"
)
CATALOG_MODULE = "mixar.bootstrap.generation_catalog_cache"


def _load_module():
    spec = spec_from_file_location("video_generation_catalog_under_test", MODULE_PATH)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _catalog_module(service):
    module = ModuleType(CATALOG_MODULE)
    module.get_service = lambda _key: service
    return module


def _service_input_spec():
    return {
        "input_spec": {
            "inputs": [
                {
                    "kind": "image",
                    "multiple": True,
                    "max_count": 7,
                },
                {
                    "kind": "video",
                    "multiple": True,
                    "max_count": 2,
                    "max_total_duration_seconds": 11,
                    "max_size_mb": 80,
                    "extensions": [".MP4", ".mov"],
                },
            ],
            "max_materials": 8,
        }
    }


def test_limits_come_from_the_catalog_service(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        CATALOG_MODULE,
        _catalog_module(_service_input_spec()),
    )

    limits = _load_module().get_video_generation_limits("video_gen")

    assert limits == {
        "max_images": 7,
        "max_videos": 2,
        "max_materials": 8,
        "max_video_seconds": 11.0,
        "max_video_bytes": 80 * 1024 * 1024,
        "video_extensions": (".mp4", ".mov"),
    }


def test_missing_catalog_limits_fail_closed(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        CATALOG_MODULE,
        _catalog_module({"input_spec": {"inputs": []}}),
    )

    assert _load_module().get_video_generation_limits("video_gen") is None

def test_non_positive_catalog_limits_fail_closed(monkeypatch):
    service = _service_input_spec()
    service["input_spec"]["inputs"][1]["max_count"] = 0
    monkeypatch.setitem(
        sys.modules,
        CATALOG_MODULE,
        _catalog_module(service),
    )

    assert _load_module().get_video_generation_limits("video_gen") is None
