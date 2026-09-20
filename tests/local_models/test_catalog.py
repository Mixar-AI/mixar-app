# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fit ladder + recommendation over the pinned model catalog."""

from mixar.modules.local_models.constants import (
    DEFAULT_MODEL_ID,
    MODEL_CATALOG,
)
from mixar.modules.local_models.core import catalog

GiB = 1024 ** 3


def test_catalog_ids_unique_and_default_present():
    ids = [entry["id"] for entry in MODEL_CATALOG]
    assert len(ids) == len(set(ids))
    assert DEFAULT_MODEL_ID in ids
    assert sum(1 for e in MODEL_CATALOG if e["is_default"]) == 1


def test_required_files_include_mmproj_only_for_vision():
    for entry in MODEL_CATALOG:
        files = catalog.required_files(entry["id"])
        expected = 2 if entry["mmproj"] else 1
        assert len(files) == expected
        for spec in files:
            assert spec["url"].startswith("https://huggingface.co/")
            assert len(spec["sha256"]) == 64
            assert spec["size"] > 0


def test_fit_ladder_unknown_when_ram_unprobed():
    for entry in MODEL_CATALOG:
        assert catalog.fit_state(entry["id"], 0) == "unknown"


def test_fit_ladder_thresholds():
    # qwen3.5-2b totals ~1.95 GB: fits at 8 GiB, tight at 4 GiB, too big at 1 GiB.
    assert catalog.fit_state("qwen3.5-2b", 8 * GiB) == "fits"
    assert catalog.fit_state("qwen3.5-2b", 4 * GiB) == "tight"
    assert catalog.fit_state("qwen3.5-2b", 1 * GiB) == "too_big"
    # qwen3.5-9b totals ~6.6 GB: tight at 8 GiB (files fit, headroom doesn't).
    assert catalog.fit_state("qwen3.5-9b", 8 * GiB) == "tight"
    assert catalog.fit_state("qwen3.5-9b", 16 * GiB) == "fits"
    # The 27B flagship (~17.7 GB files) needs a 32 GiB machine.
    assert catalog.fit_state("qwen3.6-27b", 16 * GiB) == "too_big"
    assert catalog.fit_state("qwen3.6-27b", 32 * GiB) == "fits"


def test_fit_rule_boundary_math():
    """fits iff size*1.15 + 2GiB <= ram; tight iff size <= ram."""
    size = catalog.total_bytes("qwen3.5-4b")
    exactly_fits = int(size * 1.15 + 2 * GiB) + 1
    assert catalog.fit_state("qwen3.5-4b", exactly_fits) == "fits"
    assert catalog.fit_state("qwen3.5-4b", exactly_fits - 2) == "tight"
    assert catalog.fit_state("qwen3.5-4b", size - 1) == "too_big"


def test_recommend_default_is_largest_fitting():
    # 8 GiB: 4B fits, 9B doesn't -> 4B.
    assert catalog.recommend_default(total_ram_bytes=8 * GiB) == "qwen3.5-4b"
    # 12 GiB: 9B fits (7.6+2.1 <= 12), gpt-oss-20b does not -> 9B.
    assert catalog.recommend_default(total_ram_bytes=12 * GiB) == "qwen3.5-9b"
    # 16 GiB: gpt-oss-20b (12.1 GB files) squeezes in and is the largest.
    assert catalog.recommend_default(total_ram_bytes=16 * GiB) == "gpt-oss-20b"
    # 32 GiB: the 27B flagship is the largest fit.
    assert catalog.recommend_default(total_ram_bytes=32 * GiB) == "qwen3.6-27b"


def test_recommend_default_falls_back_to_catalog_default():
    assert catalog.recommend_default(total_ram_bytes=0) == DEFAULT_MODEL_ID
    assert catalog.recommend_default(total_ram_bytes=1 * GiB) == DEFAULT_MODEL_ID


def test_list_models_computed_state():
    rows = catalog.list_models(
        total_ram_bytes=8 * GiB, downloaded_ids={"qwen3.5-2b"}
    )
    by_id = {row["id"]: row for row in rows}
    assert set(by_id) == {e["id"] for e in MODEL_CATALOG}
    assert by_id["qwen3.5-2b"]["downloaded"] is True
    assert by_id["qwen3.5-4b"]["downloaded"] is False
    assert by_id["qwen3.5-4b"]["fit"] == "fits"
    assert by_id["qwen3.6-27b"]["fit"] == "too_big"
    recommended = [row["id"] for row in rows if row["recommended"]]
    assert recommended == ["qwen3.5-4b"]
    for row in rows:
        assert row["total_bytes"] == catalog.total_bytes(row["id"])


def test_list_models_unknown_ram_shows_no_warnings():
    rows = catalog.list_models(total_ram_bytes=0, downloaded_ids=())
    assert {row["fit"] for row in rows} == {"unknown"}
