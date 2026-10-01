# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Translation helpers and the bpy.app.translations registration."""

import sys
import types

import pytest

from mixar.modules.common.i18n.core import api, runtime


class FakeTranslations:
    def __init__(self, locale="fr_FR"):
        self.locale = locale
        self.registered = {}

    def register(self, owner, data):
        if owner in self.registered:
            raise ValueError("already registered")
        self.registered[owner] = data

    def unregister(self, owner):
        self.registered.pop(owner, None)

    def _lookup(self, msgid, msgctxt=None):
        for data in self.registered.values():
            table = data.get(self.locale, {})
            value = table.get((msgctxt or "*", msgid))
            if value:
                return value
        return msgid

    pgettext_iface = pgettext_tip = pgettext_rpt = pgettext_data = _lookup


@pytest.fixture
def fake(monkeypatch, tmp_path):
    fake = FakeTranslations()
    app = types.SimpleNamespace(translations=fake, timers=types.SimpleNamespace(
        is_registered=lambda f: False, register=lambda *a, **k: None, unregister=lambda f: None),
        handlers=types.SimpleNamespace(load_post=[]))
    bpy = types.SimpleNamespace(app=app, msgbus=types.SimpleNamespace(
        clear_by_owner=lambda owner: None, subscribe_rna=lambda **k: None),
        types=types.SimpleNamespace(PreferencesView=object),
        context=types.SimpleNamespace(window_manager=types.SimpleNamespace(windows=[])))
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    monkeypatch.setitem(sys.modules, "bpy.app", app)
    monkeypatch.setattr(api, "_translations", None)
    (tmp_path / "fr_FR.po").write_text(
        'msgid ""\nmsgstr ""\n\nmsgid "Generate"\nmsgstr "Générer"\n\n'
        'msgid "{count} jobs"\nmsgstr "{count} tâches"\n', encoding="utf-8")
    (tmp_path / "de_DE.po").write_text(
        'msgid ""\nmsgstr ""\n\nmsgid "Generate"\nmsgstr "Generieren"\n', encoding="utf-8")
    monkeypatch.setattr(runtime, "LOCALE_DIR", tmp_path)
    runtime._state.update(code=None, locale=None, registered=False)
    yield fake
    runtime._state.update(code=None, locale=None, registered=False)


def test_helpers_pass_through_without_real_bpy(monkeypatch):
    # The root conftest's MagicMock bpy returns mocks, never strings.
    monkeypatch.setattr(api, "_translations", None)
    assert api.iface_("Generate") == "Generate"
    assert api.rpt_("{count} jobs").format(count=2) == "2 jobs"
    assert api.n_("Marked") == "Marked"
    assert api.iface_("") == ""
    assert api.iface_(None) is None


def test_register_loads_only_the_active_locale(fake):
    runtime.register()
    assert runtime.active_catalog() == "fr_FR"
    table = fake.registered["mixar"]["fr_FR"]
    assert table[("*", "Generate")] == "Générer"
    assert table[("Operator", "Generate")] == "Générer"
    assert api.iface_("Generate") == "Générer"
    assert api.iface_("{count} jobs").format(count=3) == "3 tâches"
    runtime.unregister()
    assert "mixar" not in fake.registered
    assert api.iface_("Generate") == "Generate"


def test_language_switch_reloads(fake):
    runtime.register()
    fake.locale = "de_DE"
    runtime._on_language_changed()
    assert runtime.active_catalog() == "de_DE"
    assert api.iface_("Generate") == "Generieren"
    fake.locale = "en_US"
    runtime._poll_locale()
    assert runtime.active_catalog() is None
    assert "mixar" not in fake.registered


def test_os_locale_alias_registers_under_the_reported_locale(fake):
    fake.locale = "fr_CA"
    runtime.register()
    assert runtime.active_catalog() == "fr_FR"
    assert set(fake.registered["mixar"]) == {"fr_CA", "fr_FR"}
    assert api.iface_("Generate") == "Générer"
