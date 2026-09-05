# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for plugin_import's bpy-free discovery / enumeration / selection.

These three modules deliberately avoid importing ``bpy`` so they can be
exercised as ordinary Python against synthetic filesystem trees.
"""

from __future__ import annotations

import pytest

from mixar.modules.plugin_import.core import discovery, source_select
from mixar.modules.plugin_import.core.enumerate import (
    list_addons,
    list_extensions,
    list_user_plugins,
)


# ---------------------------------------------------------------------------
# Fixture helpers — build a fake Blender user config tree.
# ---------------------------------------------------------------------------


def make_version(base, version):
    vdir = base / version
    vdir.mkdir(parents=True, exist_ok=True)
    return vdir


def add_addon_package(version_dir, name):
    pkg = version_dir / "scripts" / "addons" / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("# addon\n")
    return pkg


def add_addon_single_file(version_dir, name):
    addons = version_dir / "scripts" / "addons"
    addons.mkdir(parents=True, exist_ok=True)
    path = addons / f"{name}.py"
    path.write_text("# addon\n")
    return path


def add_extension(version_dir, repo, name):
    pkg = version_dir / "extensions" / repo / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "blender_manifest.toml").write_text('id = "%s"\n' % name)
    return pkg


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------


class TestBaseDirs:
    def test_macos_uses_application_support(self, tmp_path):
        bases = discovery.blender_base_dirs(platform="darwin", home=tmp_path, environ={})
        assert bases == [tmp_path / "Library" / "Application Support" / "Blender"]

    def test_windows_prefers_appdata(self, tmp_path):
        roaming = tmp_path / "Roaming"
        bases = discovery.blender_base_dirs(
            platform="win32", home=tmp_path, environ={"APPDATA": str(roaming)}
        )
        assert bases == [roaming / "Blender Foundation" / "Blender"]

    def test_windows_falls_back_when_appdata_missing(self, tmp_path):
        bases = discovery.blender_base_dirs(platform="win32", home=tmp_path, environ={})
        assert bases == [
            tmp_path / "AppData" / "Roaming" / "Blender Foundation" / "Blender"
        ]

    def test_linux_honours_xdg_config_home(self, tmp_path):
        xdg = tmp_path / "cfg"
        bases = discovery.blender_base_dirs(
            platform="linux", home=tmp_path, environ={"XDG_CONFIG_HOME": str(xdg)}
        )
        assert bases == [xdg / "blender"]

    def test_linux_defaults_to_dot_config(self, tmp_path):
        bases = discovery.blender_base_dirs(platform="linux", home=tmp_path, environ={})
        assert bases == [tmp_path / ".config" / "blender"]


class TestFindSourceVersions:
    def test_orders_newest_first(self, tmp_path):
        for v in ("4.2", "5.0", "4.10"):
            make_version(tmp_path, v)
        found = discovery.find_source_versions(bases=[tmp_path])
        # 4.10 must sort above 4.2 — numeric compare, not string compare.
        assert [v for v, _ in found] == ["5.0", "4.10", "4.2"]

    def test_ignores_non_version_dirs_and_files(self, tmp_path):
        make_version(tmp_path, "5.0")
        (tmp_path / "notaversion").mkdir()
        (tmp_path / "5.1").write_text("a file, not a dir")
        assert [v for v, _ in discovery.find_source_versions(bases=[tmp_path])] == ["5.0"]

    def test_missing_base_is_not_an_error(self, tmp_path):
        assert discovery.find_source_versions(bases=[tmp_path / "nope"]) == []

    def test_newest_source_version_returns_none_when_empty(self, tmp_path):
        assert discovery.newest_source_version(bases=[tmp_path]) is None


# ---------------------------------------------------------------------------
# enumerate
# ---------------------------------------------------------------------------


class TestListAddons:
    def test_finds_packages_and_single_files(self, tmp_path):
        v = make_version(tmp_path, "5.0")
        add_addon_package(v, "my_addon")
        add_addon_single_file(v, "loose_addon")
        names = sorted(p.name for p in list_addons(v))
        assert names == ["loose_addon", "my_addon"]

    def test_skips_package_dir_without_init(self, tmp_path):
        v = make_version(tmp_path, "5.0")
        (v / "scripts" / "addons" / "broken").mkdir(parents=True)
        assert list_addons(v) == []

    def test_skips_pycache_and_dotfiles(self, tmp_path):
        v = make_version(tmp_path, "5.0")
        add_addon_package(v, "__pycache__")
        add_addon_package(v, ".hidden")
        add_addon_package(v, "real")
        assert [p.name for p in list_addons(v)] == ["real"]

    def test_missing_addons_dir_returns_empty(self, tmp_path):
        assert list_addons(make_version(tmp_path, "5.0")) == []


class TestListExtensions:
    def test_scans_every_repo_including_blender_org(self, tmp_path):
        v = make_version(tmp_path, "5.0")
        add_extension(v, "blender_org", "node_wrangler")
        add_extension(v, "user_default", "blenderkit")
        found = {p.name: p.source_repo for p in list_extensions(v)}
        assert found == {"node_wrangler": "blender_org", "blenderkit": "user_default"}

    def test_requires_a_manifest(self, tmp_path):
        v = make_version(tmp_path, "5.0")
        (v / "extensions" / "user_default" / "nomanifest").mkdir(parents=True)
        assert list_extensions(v) == []

    def test_skips_repo_cache_dirs(self, tmp_path):
        v = make_version(tmp_path, "5.0")
        add_extension(v, "user_default", ".blender_ext")
        add_extension(v, ".cache", "whatever")
        add_extension(v, "user_default", "real")
        assert [p.name for p in list_extensions(v)] == ["real"]


class TestListUserPlugins:
    def test_extensions_come_before_addons(self, tmp_path):
        v = make_version(tmp_path, "5.0")
        add_addon_package(v, "an_addon")
        add_extension(v, "user_default", "an_extension")
        kinds = [p.kind for p in list_user_plugins(v)]
        assert kinds == ["extension", "addon"]

    def test_label_titlecases_underscored_names(self, tmp_path):
        v = make_version(tmp_path, "5.0")
        add_addon_package(v, "node_wrangler")
        assert list_user_plugins(v)[0].label == "Node Wrangler"


# ---------------------------------------------------------------------------
# source_select — the empty-newest-version regression
# ---------------------------------------------------------------------------


class TestSelectSource:
    def test_skips_newer_empty_version_for_populated_older_one(self, tmp_path):
        """The regression: Blender makes 5.1's config dir on first launch,
        leaving it empty while every plugin still lives under 5.0."""
        make_version(tmp_path, "5.1")
        older = make_version(tmp_path, "5.0")
        add_extension(older, "user_default", "blenderkit")

        choice = source_select.select_source(bases=[tmp_path])

        assert choice is not None
        assert choice.version == "5.0"
        assert choice.has_plugins
        assert [p.name for p in choice.plugins] == ["blenderkit"]

    def test_newest_wins_when_both_have_plugins(self, tmp_path):
        newer = make_version(tmp_path, "5.1")
        older = make_version(tmp_path, "5.0")
        add_extension(newer, "user_default", "new_one")
        add_extension(older, "user_default", "old_one")

        choice = source_select.select_source(bases=[tmp_path])
        assert choice.version == "5.1"

    def test_none_when_no_blender_installed(self, tmp_path):
        assert source_select.select_source(bases=[tmp_path]) is None

    def test_installed_but_empty_is_distinguishable_from_absent(self, tmp_path):
        """Onboarding needs these two cases to read differently: 'no Blender
        found' vs 'Blender found, nothing to import'."""
        make_version(tmp_path, "5.0")

        choice = source_select.select_source(bases=[tmp_path])

        assert choice is not None          # Blender IS installed...
        assert not choice.has_plugins      # ...but has nothing to offer.
        assert choice.version == "5.0"

    @pytest.mark.parametrize("populated", [True, False])
    def test_has_importable_plugins_tracks_plugin_presence(self, tmp_path, populated):
        v = make_version(tmp_path, "5.0")
        if populated:
            add_addon_package(v, "something")
        assert source_select.has_importable_plugins(bases=[tmp_path]) is populated
