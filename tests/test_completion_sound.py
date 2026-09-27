# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Task-completion sound selection contract.

The sounds are backend-driven (``space_mixie_chat/core/sound_catalog.py``) with
a bundled ``CHIME`` as the offline fallback and a master mute. This pins the
pure selection/fallback/mute logic without touching real config, bpy or audio.

Contract:
* the picker is ``Off``, built-in ``Chime``, then the catalog sounds;
* an unknown/removed stored value (e.g. the retired ``MEOW``) falls back to the
  ``CHIME`` default;
* ``OFF`` and an active mute both play nothing; mute never blocks Preview;
* a built-in sound plays its bundled asset; a catalog sound with no cached clip
  never plays synchronously (it downloads on a worker first).
"""

import importlib

import pytest

completion_sound = importlib.import_module(
    "mixar.modules.space_mixie_chat.core.completion_sound"
)


@pytest.fixture
def cs(monkeypatch):
    """completion_sound with in-memory config and a controllable catalog."""
    store = {}
    monkeypatch.setattr(completion_sound, "get_config", lambda: store)

    def _add(key, value):
        store[key] = value
        return True

    monkeypatch.setattr(completion_sound, "add_config", _add)

    catalog = []
    sc = completion_sound.sound_catalog
    monkeypatch.setattr(sc, "get_sounds", lambda: list(catalog))
    monkeypatch.setattr(
        sc, "find_sound",
        lambda sid: next((s for s in catalog if s["id"] == sid), None),
    )
    monkeypatch.setattr(sc, "cached_clip_path", lambda sid: None)

    played = []
    monkeypatch.setattr(completion_sound, "_play_file", lambda p: played.append(p))
    return completion_sound, store, catalog, played


def test_picker_without_catalog(cs):
    mod, _store, _catalog, _played = cs
    assert mod.available_sounds() == [("OFF", "Off"), ("CHIME", "Chime")]
    assert mod.get_completion_sound() == "CHIME"


def test_stale_value_falls_back_to_default(cs):
    mod, store, _catalog, _played = cs
    store["completion_sound"] = "MEOW"  # retired option
    assert mod.get_completion_sound() == "CHIME"


def test_catalog_extends_picker(cs):
    mod, _store, catalog, _played = cs
    catalog.extend([
        {"id": "ping", "label": "Ping", "url": "u1"},
        {"id": "boop", "label": "Boop", "url": "u2"},
    ])
    assert mod.available_sounds() == [
        ("OFF", "Off"), ("CHIME", "Chime"), ("ping", "Ping"), ("boop", "Boop"),
    ]
    assert mod.set_completion_sound("ping")
    assert mod.get_completion_sound() == "ping"


def test_mute_silences_completion_sound(cs):
    mod, _store, _catalog, played = cs
    mod.set_completion_sound("CHIME")
    mod.set_notifications_muted(True)
    mod.play_completion_sound()
    assert played == []
    # Preview (play_sound directly) still plays while muted.
    mod.play_sound("CHIME")
    assert played and played[0].endswith("task_complete.mp3")


def test_off_plays_nothing(cs):
    mod, _store, _catalog, played = cs
    mod.set_completion_sound("OFF")
    mod.play_completion_sound()
    assert played == []


def test_builtin_chime_plays_bundled_asset(cs):
    mod, _store, _catalog, played = cs
    mod.set_completion_sound("CHIME")
    mod.play_completion_sound()
    assert played and played[0].endswith("task_complete.mp3")


def test_uncached_catalog_sound_does_not_play_sync(cs, monkeypatch):
    mod, _store, catalog, played = cs
    catalog.append({"id": "ping", "label": "Ping", "url": "u1"})
    # No cached clip and no worker download -> nothing plays synchronously.
    monkeypatch.setattr(
        mod, "threading",
        type("T", (), {"Thread": staticmethod(lambda **k: type(
            "X", (), {"start": lambda self: None})())})(),
    )
    mod.set_completion_sound("ping")
    mod.play_completion_sound()
    assert played == []
