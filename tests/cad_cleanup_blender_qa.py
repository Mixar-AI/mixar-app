# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Exercise real CAD tools inside an isolated Blender/Mixar process.

Example: blender --background --factory-startup --python this_file.py --
         --out D:/metadome/_cad_work/evidence/blender

Leaves the generated QA scene active for GUI screenshot inspection. Never opens
or resets a vehicle file; requires an unsaved session unless the caller explicitly
declares it an isolated QA app. Review/save is a separate call after looking at
the generated evidence PNG, so the fixture cannot pretend vision review occurred.
"""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys

import bpy

CLIENT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT_ROOT / "src/scripts"))
sys.path.insert(0, str(Path(__file__).parent))
from cad_cleanup_fixture import build_fixture, snapshot
from mixar.modules.common.cad_cleanup.api import dispatch

STAGES = ("1", "2", "3", "4", "5", "5b", "6", "7", "8", "8b", "9", "10")
OWNER = "qa-cad"
ACTIVE = {}


def call(action, **payload):
    result = dispatch(action, {"owner_id": OWNER, **payload})
    assert result.get("success") is True, (action, result)
    return result


def refused(action, **payload):
    result = dispatch(action, {"owner_id": OWNER, **payload})
    assert result.get("success") is False, (action, result)
    assert result.get("error"), result
    return result


def run_geometry_checks(output_dir, isolated=False):
    if bpy.data.filepath and not isolated:
        raise RuntimeError("Run in a fresh --factory-startup process; no user file may be active")
    directory = Path(output_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    fixture = build_fixture()
    source = directory / ("cad-fixture-source-" + fixture["token"] + ".blend")
    assert not source.exists()
    bpy.ops.wm.save_as_mainfile(filepath=str(source), check_existing=False)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    initial = snapshot(fixture["objects"])
    start = call("start", request_id="start-" + fixture["token"],
                 root_collection=fixture["root"].name)
    run_id = start["run_id"]
    common = {"run_id": run_id}
    second = call("start", request_id="start-" + fixture["token"],
                  root_collection=fixture["root"].name)
    assert second["run_id"] == run_id, "start retry created a second run"
    denied = dispatch("status", {"owner_id": "another-agent", **common})
    assert denied["success"] is False, denied
    inspected = call("inspect", **common)
    records = inspected["objects"]
    names = {r["name"] for r in records}
    assert "OUTSIDE ENGINE BLOCK" not in names
    expected = set(fixture["objects"]) - {"OUTSIDE ENGINE BLOCK"}
    assert expected <= names, sorted(expected - names)
    assert len({r["object_id"] for r in records}) == len(records)
    refused("save", **common, request_id="premature-save", filename="premature.blend")
    results = []
    for stage in STAGES:
        before = snapshot(fixture["objects"])
        analyzed = call("analyze", **common, stage=stage)
        assert snapshot(fixture["objects"]) == before, "analysis mutated scene: " + stage
        payload = {**common, "proposal_id": analyzed["proposal_id"],
                   "request_id": "apply-" + stage}
        applied = call("apply", **payload)
        retry = call("apply", **payload)
        assert retry["operation_id"] == applied["operation_id"], "apply retry duplicated work"
        assert retry["revision"] == applied["revision"]
        after = snapshot(fixture["objects"])
        assert after["OUTSIDE ENGINE BLOCK"] == initial["OUTSIDE ENGINE BLOCK"]
        for name in ("QA topology A", "QA topology B", "QA rotated duplicate", "QA UV variant"):
            assert after[name]["faces"] == initial[name]["faces"], (stage, name)
            assert after[name]["matrix"] == initial[name]["matrix"], (stage, name)
            assert after[name]["uv"] == initial[name]["uv"], (stage, name)
            assert after[name]["material_indices"] == initial[name]["material_indices"], (stage, name)
        for name in expected:
            assert after[name]["hide_render"] == initial[name]["hide_render"], (stage, name)
            for actual, original in zip(after[name]["world_vertices"], initial[name]["world_vertices"]):
                assert max(abs(a - b) for a, b in zip(actual, original)) < 1e-5, (stage, name)
        if stage == "9":
            call("undo", **common, operation_id=applied["operation_id"], request_id="undo-9")
            reverted = snapshot(fixture["objects"])
            for name in expected:
                assert reverted[name]["collections"] == before[name]["collections"], name
            analyzed = call("analyze", **common, stage=stage)
            applied = call("apply", **common, proposal_id=analyzed["proposal_id"],
                           request_id="reapply-9")
        results.append({"stage": stage, "operation_id": applied["operation_id"],
                        "changed_count": applied["changed_count"]})
    verified = call("verify", **common)
    assert verified["verified"], verified
    refused("save", **common, request_id="unreviewed-save", filename="unreviewed.blend")
    rendered = call("render", **common, view="perspective")
    encoded = rendered["image_base64"]
    image_bytes = base64.b64decode(encoded.split(",", 1)[-1])
    assert image_bytes.startswith(b"\x89PNG\r\n\x1a\n"), "render did not return PNG"
    evidence_png = directory / "cad-cleanup-evidence.png"
    evidence_png.write_bytes(image_bytes)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    assert bpy.data.filepath == str(source)
    report = {"success": True, "run_id": run_id, "owner_id": OWNER,
              "source": str(source), "source_sha256": source_hash,
              "stages": results, "verification": verified,
              "evidence_id": rendered["evidence_id"], "evidence_png": str(evidence_png),
              "visual_review_pending": True, "output_saved": False,
              "object_count": len(expected)}
    ACTIVE.update({"fixture": fixture, "report": report, "directory": directory})
    (directory / "cad-cleanup-qa.json").write_text(json.dumps(report, indent=2))
    return report


def finish_after_visual_review(notes):
    """Call only AFTER an agent/human has actually inspected evidence_png."""
    assert isinstance(notes, str) and len(notes.strip()) >= 10
    report = ACTIVE["report"]
    common = {"run_id": report["run_id"]}
    call("review", **common, evidence_id=report["evidence_id"], verdict="pass", notes=notes)
    # Source/output collisions and path traversal must fail even after all gates pass.
    refused("save", **common, request_id="source-collision", filename=Path(report["source"]).name)
    refused("save", **common, request_id="traversal", filename="../cad-escaped.blend")
    filename = "cad-fixture-cleaned-" + ACTIVE["fixture"]["token"] + ".blend"
    saved = call("save", **common, request_id="final-save", filename=filename)
    retried = call("save", **common, request_id="final-save", filename=filename)
    assert retried == saved, "save retry was not idempotent"
    output = ACTIVE["directory"] / filename
    assert output.is_file() and output.stat().st_size > 0
    assert hashlib.sha256(Path(report["source"]).read_bytes()).hexdigest() == report["source_sha256"]
    assert bpy.data.filepath == report["source"], "save changed source identity"
    status = call("status", **common)
    assert status["saved"] is True, status
    report.update({"visual_review_pending": False, "visual_review_notes": notes,
                   "output_saved": True, "artifact": status["artifact"], "output": str(output)})
    (ACTIVE["directory"] / "cad-cleanup-qa.json").write_text(json.dumps(report, indent=2))
    return report


def check_saved_reopen():
    """Reopen ONLY the generated fixture output and test persisted resume/replay."""
    report = dict(ACTIVE["report"])
    assert report["output_saved"] and not report["visual_review_pending"]
    destination = Path(report["output"])
    assert destination.parent == ACTIVE["directory"]
    assert destination.name.startswith("cad-fixture-cleaned-")
    bpy.ops.wm.open_mainfile(filepath=str(destination))
    common = {"run_id": report["run_id"]}
    resumed = call("start", **common, request_id="reopened-fixture")
    assert resumed["run_id"] == report["run_id"]
    status = call("status", **common)
    assert status["saved"] and status["verified"], status
    assert all(value == "reviewed" for value in status["stage_status"].values())
    retried = call("save", **common, request_id="final-save", filename=destination.name)
    assert retried["artifact"]["artifact_id"] == report["artifact"]["artifact_id"]
    assert hashlib.sha256(Path(report["source"]).read_bytes()).hexdigest() == report["source_sha256"]
    report["reopen_and_saved_request_replay"] = True
    (ACTIVE["directory"] / "cad-cleanup-qa.json").write_text(json.dumps(report, indent=2))
    ACTIVE["report"] = report
    return report


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(run_geometry_checks(args.out), indent=2))
