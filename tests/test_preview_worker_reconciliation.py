# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A crashed worker shard must turn its unrendered assets into failures.

``_poll_shard`` marks a shard terminal when the process has exited and no new
result lines arrive — regardless of whether it produced its full count. A
shard that dies after >=1 result line (OOM kill, segfault on a malformed
asset) therefore leaves its remainder with NO result line and NO failure
entry: the run completed "cleanly", ``complete()`` saw an empty failure list
and stamped the full-library ``metadata_checksum`` — the server then marks
those assets trained and they become unreachable until their .blend changes.

The contract pinned here: ``missing_result_failures`` reconciles every
shard's result count against its plan and reports the unrendered assets as
failures (so the checksum stays unstamped and the next train retries them),
with a count-based fallback when the shard plan is unreadable.

Plan items are the discovery dicts (``kind``/``blend_str``/``name``/
``library``/``rel_path`` — see ``render_session``); the worker labels each
result ``"{name} ({library})"``, so reconciliation must build the same label
from the same keys or nothing ever matches.
"""

import json
from types import SimpleNamespace

from mixar.modules.asset_search.core import preview_worker


def _shard(work_dir, name, total, results):
    shard = preview_worker._Shard(
        SimpleNamespace(poll=lambda: 1, pid=0), str(work_dir / name), total
    )
    shard.results = list(results)
    return shard


def _item(name, library="Props", blend="/lib/props.blend"):
    """A plan item exactly as ``render_session`` discovers it."""
    return {
        "kind": "OBJECT",
        "blend_str": blend,
        "name": name,
        "library": library,
        "rel_path": "props.blend",
    }


def _label(item):
    """The worker's result label for a plan item (preview_worker_script)."""
    return f"{item.get('name', '?')} ({item.get('library', '?')})"


def _write_plan(base, name, items):
    shard_dir = base / name
    shard_dir.mkdir(parents=True, exist_ok=True)
    with open(shard_dir / "plan.json", "w", encoding="utf-8") as fh:
        json.dump({"items": items, "out_dir": str(shard_dir)}, fh)


def test_crashed_shard_reports_unrendered_assets_as_failures(tmp_path):
    alpha, beta, gamma = _item("Alpha"), _item("Beta"), _item("Gamma")
    _write_plan(tmp_path, "shard_00", [alpha, beta, gamma])
    healthy = _shard(tmp_path, "shard_01", 2, [
        {"ok": True, "label": _label(_item("Delta"))},
        {"ok": True, "label": _label(_item("Epsilon"))},
    ])
    crashed = _shard(tmp_path, "shard_00", 3, [
        {"ok": True, "label": _label(alpha)},
    ])
    handle = preview_worker.WorkerHandle(str(tmp_path), [crashed, healthy])

    failures = preview_worker.missing_result_failures(handle)

    # The REAL labels are recorded — "Beta (Props)", not a placeholder.
    assert ("Beta (Props)", "preview worker exited before rendering this asset") in failures
    assert ("Gamma (Props)", "preview worker exited before rendering this asset") in failures
    # Healthy shards contribute nothing.
    assert len(failures) == 2


def test_failed_result_lines_count_as_produced(tmp_path):
    alpha, beta = _item("Alpha"), _item("Beta")
    _write_plan(tmp_path, "shard_00", [alpha, beta])
    # The shard DID report Beta — as a failure. Both items are accounted for.
    crashed = _shard(tmp_path, "shard_00", 2, [
        {"ok": True, "label": _label(alpha)},
        {"ok": False, "label": _label(beta), "reason": "no mesh"},
    ])
    handle = preview_worker.WorkerHandle(str(tmp_path), [crashed])

    assert preview_worker.missing_result_failures(handle) == []


def test_same_name_in_two_libraries_is_told_apart(tmp_path):
    # Two "Chair" assets from different libraries share a shard; only the
    # library half of the label distinguishes the rendered from the missing.
    rendered = _item("Chair", library="Kitchen", blend="/lib/kitchen.blend")
    missing = _item("Chair", library="Office", blend="/lib/office.blend")
    _write_plan(tmp_path, "shard_00", [rendered, missing])
    crashed = _shard(tmp_path, "shard_00", 2, [
        {"ok": True, "label": _label(rendered)},
    ])
    handle = preview_worker.WorkerHandle(str(tmp_path), [crashed])

    assert preview_worker.missing_result_failures(handle) == [
        ("Chair (Office)", "preview worker exited before rendering this asset"),
    ]


def test_label_falls_back_to_placeholder_only_for_absent_keys(tmp_path):
    # A plan item without name/library still gets the worker's "?" halves
    # (the worker uses the same defaults), never a KeyError.
    _write_plan(tmp_path, "shard_00", [_item("Alpha"), {"kind": "OBJECT"}])
    crashed = _shard(tmp_path, "shard_00", 2, [
        {"ok": True, "label": _label(_item("Alpha"))},
    ])
    handle = preview_worker.WorkerHandle(str(tmp_path), [crashed])

    assert preview_worker.missing_result_failures(handle) == [
        ("? (?)", "preview worker exited before rendering this asset"),
    ]


def test_unreadable_plan_falls_back_to_a_count_entry(tmp_path):
    # No plan.json on disk for this shard.
    crashed = _shard(tmp_path, "shard_00", 4, [
        {"ok": True, "label": _label(_item("Alpha"))},
    ])
    handle = preview_worker.WorkerHandle(str(tmp_path), [crashed])

    failures = preview_worker.missing_result_failures(handle)

    assert failures == [(
        "worker shard",
        "3 assets were not rendered (worker exited early)",
    )]


def test_complete_handle_reports_nothing(tmp_path):
    alpha, beta = _item("Alpha"), _item("Beta")
    _write_plan(tmp_path, "shard_00", [alpha, beta])
    shard = _shard(tmp_path, "shard_00", 2, [
        {"ok": True, "label": _label(alpha)},
        {"ok": True, "label": _label(beta)},
    ])
    handle = preview_worker.WorkerHandle(str(tmp_path), [shard])

    assert preview_worker.missing_result_failures(handle) == []
