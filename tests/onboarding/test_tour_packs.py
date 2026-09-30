# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The pack cache: a pack is installed only when everything is verified,
and the media resolver falls back to English otherwise."""

import hashlib
import json
import sys
from unittest.mock import MagicMock

if "requests" not in sys.modules:
    sys.modules["requests"] = MagicMock(name="requests")

from mixar.modules.onboarding.core.tour import config, media, packs, timing  # noqa: E402
from mixar.modules.onboarding.core.tour.beats import MIXAR_INTRO  # noqa: E402

from test_tour_timing import table_from  # noqa: E402


def _write(path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def make_pack(root, code="fr", verified=True, script_hash=None, pack_version=None):
    table = table_from(MIXAR_INTRO)
    if script_hash is not None:
        table["script_hash"] = script_hash
    t_bytes = json.dumps(table).encode()
    t_sha = _write(root / code / "timing.json", t_bytes)
    parts, start = [], 0
    for k in range(3):
        data = f"video-{k}".encode()
        sha = _write(root / code / f"part-{k}.mp4", data)
        parts.append({"k": k, "url": f"https://cdn/{code}/part-{k}.mp4", "sha256": sha,
                      "bytes": len(data), "start_ms": start, "end_ms": start + 1000})
        start += 1000
        if verified:
            packs.mark_verified(str(root / code / f"part-{k}.mp4"), sha)
    if verified:
        packs.mark_verified(str(root / code / "timing.json"), t_sha)
    manifest = {"pack_version": config.TOUR_PACK_VERSION if pack_version is None else pack_version,
                "languages": {code: {"code": code, "duration_ms": start, "parts": parts,
                                     "timing": {"url": "https://cdn/t", "sha256": t_sha}}}}
    (root / "manifest.json").write_text(json.dumps(manifest))
    return manifest


def test_complete_verified_pack_is_installed(tmp_path):
    make_pack(tmp_path)
    info = packs.installed("fr", root=str(tmp_path))
    assert info is not None
    assert [p[:2] for p in info.parts] == [(0, 1000), (1000, 2000), (2000, 3000)]
    assert info.duration_ms == 3000


def test_unverified_files_mean_not_installed(tmp_path):
    make_pack(tmp_path, verified=False)
    assert packs.installed("fr", root=str(tmp_path)) is None
    manifest = packs.read_manifest(str(tmp_path))
    entry = packs.manifest_entry(manifest, "fr")
    missing = packs.missing_files(str(tmp_path), entry, "fr")
    assert [m[1].rsplit("/", 1)[-1] for m in missing] == [
        "timing.json", "part-0.mp4", "part-1.mp4", "part-2.mp4"]


def test_other_pack_version_or_script_is_ignored(tmp_path):
    make_pack(tmp_path, pack_version=config.TOUR_PACK_VERSION + 1)
    assert packs.installed("fr", root=str(tmp_path)) is None
    make_pack(tmp_path, script_hash="0000")
    assert packs.installed("fr", root=str(tmp_path)) is None


def test_english_is_never_a_pack(tmp_path):
    make_pack(tmp_path, code="en")
    assert packs.installed("en", root=str(tmp_path)) is None


def test_resolve_english_user(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "video_path", lambda: "/bundle/founder.mp4")
    plan = media.resolve(MIXAR_INTRO, "en", root=str(tmp_path))
    assert plan.narration == "en" and plan.parts is None
    assert plan.video_paths == ("/bundle/founder.mp4",)
    assert plan.tour is MIXAR_INTRO


def test_resolve_falls_back_without_a_pack(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "video_path", lambda: "/bundle/founder.mp4")
    plan = media.resolve(MIXAR_INTRO, "fr", root=str(tmp_path))
    assert plan.narration == "en" and plan.tour is MIXAR_INTRO


def test_resolve_uses_a_complete_pack(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "video_path", lambda: "/bundle/founder.mp4")
    make_pack(tmp_path)
    plan = media.resolve(MIXAR_INTRO, "fr", root=str(tmp_path))
    assert plan.narration == "fr"
    assert len(plan.video_paths) == 3 and plan.video_paths[0].endswith("part-0.mp4")
    assert plan.tour.beats[1].enter_ms == int(MIXAR_INTRO.beats[1].enter_ms * 1.3) + 500
    assert plan.duration_ms == 3000


def test_resolve_rejects_a_bad_timing_table(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "video_path", lambda: "/bundle/founder.mp4")
    make_pack(tmp_path)
    # Corrupt the table after the sidecar was written: installed() still
    # sees verified files, apply() must refuse.
    path = tmp_path / "fr" / "timing.json"
    table = json.loads(path.read_text())
    table["beats"]["viewport"]["enter_ms"] = 1
    path.write_text(json.dumps(table))
    plan = media.resolve(MIXAR_INTRO, "fr", root=str(tmp_path))
    assert plan.narration == "en"


def test_qa_pack_dir_verifies_by_hashing_when_sidecars_are_missing(tmp_path, monkeypatch):
    make_pack(tmp_path, verified=False)
    monkeypatch.setenv(config.ENV_PACK_DIR, str(tmp_path))
    assert packs.installed("fr", root=str(tmp_path)) is not None
    (tmp_path / "fr" / "part-1.mp4").write_bytes(b"tampered")
    assert packs.installed("fr", root=str(tmp_path)) is None


def test_partial_pack_plays_when_timing_and_first_part_are_verified(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "video_path", lambda: "/bundle/founder.mp4")
    make_pack(tmp_path, verified=False)
    root = str(tmp_path)
    manifest = packs.read_manifest(root)
    entry = packs.manifest_entry(manifest, "fr")
    packs.mark_verified(packs.timing_path(root, "fr"), entry["timing"]["sha256"])
    # Timing alone is not enough.
    assert packs.partial("fr", root=root) is None
    assert media.resolve(MIXAR_INTRO, "fr", root=root).narration == "en"
    packs.mark_verified(packs.part_path(root, "fr", 0), entry["parts"][0]["sha256"])
    info = packs.partial("fr", root=root)
    assert info is not None and info.ready(0) and not info.ready(1)
    plan = media.resolve(MIXAR_INTRO, "fr", root=root)
    assert plan.narration == "fr" and plan.ready(0) and not plan.ready(1)
    assert media.resolve(MIXAR_INTRO, "fr", root=root, allow_partial=False).narration == "en"
    packs.mark_verified(packs.part_path(root, "fr", 1), entry["parts"][1]["sha256"])
    assert plan.ready(1)                      # readiness is read live


def test_regional_choice_uses_existing_voice_pack_and_suppresses_english_timed_subtitles(tmp_path):
    from mixar.modules.onboarding.core.tour.session_lifecycle import _subtitles_for
    for choice, voice in (("pt_BR", "pt"), ("zh_HANT", "zh")):
        make_pack(tmp_path, code=voice)
        plan = media.resolve(MIXAR_INTRO, choice, root=str(tmp_path))
        assert plan.narration == voice and plan.parts
        assert _subtitles_for(choice, plan.narration) is None
