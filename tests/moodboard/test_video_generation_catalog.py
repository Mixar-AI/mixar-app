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


def _catalog_module(service, models=None):
    module = ModuleType(CATALOG_MODULE)
    module.get_service = lambda _key: service
    module.get_model = lambda _key, slug: (models or {}).get(slug)
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
        "max_image_bytes": 30 * 1024 * 1024,
        "video_extensions": (".mp4", ".mov"),
    }


def test_image_size_cap_comes_from_catalog_when_present(monkeypatch):
    service = _service_input_spec()
    service["input_spec"]["inputs"][0]["max_size_mb"] = 12
    monkeypatch.setitem(
        sys.modules,
        CATALOG_MODULE,
        _catalog_module(service),
    )

    limits = _load_module().get_video_generation_limits("video_gen")

    assert limits["max_image_bytes"] == 12 * 1024 * 1024


def test_frame_modes_require_exact_image_counts():
    limits = {
        "max_images": 30,
        "max_videos": 10,
        "max_materials": 50,
    }
    error = _load_module().video_reference_count_error
    assert error(limits, image_count=1, video_count=0, image_mode="first_frame") is None
    assert error(limits, image_count=2, video_count=0, image_mode="first_frame")
    assert error(limits, image_count=2, video_count=0, image_mode="first_last_frame") is None
    assert error(limits, image_count=1, video_count=1, image_mode="first_frame")
    assert error(limits, image_count=8, video_count=0, image_mode="reference") is None
    tight = {**limits, "max_images": 7}
    assert "at most 7" in error(tight, image_count=8, video_count=0)


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


# --- per-model reference ceilings --------------------------------------------
#
# `video_gen` serves models whose reference ceilings differ by more than 3x
# (Seedance 30 images, MiniMax H3 9), and `input_spec` is SERVICE-level. A
# model publishes its own as `reference_limits` and they narrow the service
# spec here. Getting this wrong is not cosmetic: the submit operators compress
# and upload every reference BEFORE the backend sees the payload.


def test_a_models_own_ceilings_narrow_the_service_spec(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        CATALOG_MODULE,
        _catalog_module(
            _service_input_spec(),
            models={
                "minimax-h3": {
                    "reference_limits": {
                        "max_images": 3,
                        "max_videos": 1,
                        "max_materials": 4,
                        "max_video_seconds": 6,
                    }
                }
            },
        ),
    )

    limits = _load_module().get_video_generation_limits("video_gen", "minimax-h3")

    assert limits["max_images"] == 3
    assert limits["max_videos"] == 1
    assert limits["max_materials"] == 4
    assert limits["max_video_seconds"] == 6.0
    # Byte caps and extensions stay the service's — they are what the upload
    # endpoint itself validates against.
    assert limits["max_video_bytes"] == 80 * 1024 * 1024
    assert limits["video_extensions"] == (".mp4", ".mov")


def test_a_model_never_widens_the_service_spec(monkeypatch):
    """The service input_spec is what the upload endpoint validates against,
    so widening here would move the rejection to a charged job."""
    monkeypatch.setitem(
        sys.modules,
        CATALOG_MODULE,
        _catalog_module(
            _service_input_spec(),
            models={"greedy": {"reference_limits": {"max_images": 99}}},
        ),
    )

    limits = _load_module().get_video_generation_limits("video_gen", "greedy")

    assert limits["max_images"] == 7


def test_a_model_without_published_ceilings_keeps_the_service_spec(monkeypatch):
    """Seedance and every model that predates the field."""
    monkeypatch.setitem(
        sys.modules,
        CATALOG_MODULE,
        _catalog_module(_service_input_spec(), models={"seedance-2-5": {}}),
    )

    module = _load_module()
    assert module.get_video_generation_limits(
        "video_gen", "seedance-2-5"
    ) == module.get_video_generation_limits("video_gen")


def test_malformed_published_ceilings_are_ignored(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        CATALOG_MODULE,
        _catalog_module(
            _service_input_spec(),
            models={
                "broken": {
                    "reference_limits": {
                        "max_images": "three", "max_videos": 0, "max_materials": True,
                    }
                }
            },
        ),
    )

    limits = _load_module().get_video_generation_limits("video_gen", "broken")

    assert limits["max_images"] == 7
    assert limits["max_videos"] == 2
    assert limits["max_materials"] == 8
