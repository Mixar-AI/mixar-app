# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Digest compatibility and complete bulk animation change detection."""
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from mixar.modules.common.utils.digests import sha256, sha256_file

# Load the pure fingerprint module without starting the chat connection package.
_path = Path(__file__).parents[1] / "src/scripts/mixar/modules/space_mixie_chat/core/animation_effects.py"
_spec = importlib.util.spec_from_file_location(
    "mixar.modules.space_mixie_chat.core.animation_effects", _path)
effects = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(effects)


@pytest.mark.parametrize("payload", [b"", b"abc", b"\0a\0b\0" * 500000])
def test_stream_and_file_sha256_match_existing_checkpoints(tmp_path, payload):
    path = tmp_path / "checkpoint.mixar"
    path.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()
    digest = sha256(payload[:17])
    digest.update(memoryview(payload)[17:])
    assert digest.finalize().hex() == expected
    assert sha256_file(path) == expected


def test_binary_fingerprint_is_small_and_detects_same_length_edit():
    payload = b"\x00\xffabc" * 100000
    owner = {"gaussian_data": payload, "nested": {"bytes": payload}}
    before = effects._custom(owner)
    assert len(repr(before)) < 300
    owner["gaussian_data"] = b"x" + payload[1:]
    assert effects._custom(owner) != before
    owner["gaussian_data"] = payload
    owner["nested"]["bytes"] = payload[:-1] + b"y"
    assert effects._custom(owner) != before
    assert effects._custom({"blob": b""}) != effects._custom({"blob": ""})


class BulkPoints:
    def __init__(self, count=2):
        self.count = count
        self.fields = {
            key: [0.0] * (count * 2) for key in ("co", "handle_left", "handle_right")
        }
        for key in ("interpolation", "easing", "handle_left_type", "handle_right_type"):
            self.fields[key] = [0] * count
        for key in ("amplitude", "back", "period"):
            self.fields[key] = [0.0] * count

    def __len__(self):
        return self.count

    def __iter__(self):
        raise AssertionError("Fingerprints must not iterate individual RNA keys")

    def foreach_get(self, field, output):
        for i, value in enumerate(self.fields[field]):
            output[i] = value


@pytest.mark.parametrize("collection,field", [
    ("keyframe_points", field) for field in (
        "co", "handle_left", "handle_right", "interpolation", "easing",
        "handle_left_type", "handle_right_type", "amplitude", "back", "period"
    )
] + [("sampled_points", "co")])
def test_bulk_curve_detects_every_previously_tracked_key_setting(collection, field):
    curve = SimpleNamespace(
        data_path="location", array_index=0, bl_rna=SimpleNamespace(properties=[]),
        keyframe_points=BulkPoints(), sampled_points=BulkPoints(), modifiers=[], driver=None,
    )
    before = effects._curve(curve)
    getattr(curve, collection).fields[field][-1] = 1
    assert effects._curve(curve) != before
    getattr(curve, collection).fields[field][-1] = 0
    assert effects._curve(curve) == before
