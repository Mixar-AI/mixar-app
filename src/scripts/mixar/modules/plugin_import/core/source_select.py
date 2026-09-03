# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pick which installed Blender version to import plugins from.

Splits the two questions callers actually ask, which
:func:`discovery.newest_source_version` conflates:

- "Is any Blender installed at all?"
- "Is there anything worth importing?"

Newest-by-version-number is the wrong answer to the second one. Blender
creates a version's config dir on first launch, so immediately after an
upgrade the newest dir exists and is empty while every plugin the user
cares about is still under the previous version. Onboarding must not
tell someone with a fully populated Blender 5.0 that no Blender was
found because an empty 5.1 exists.

So: prefer the newest version that actually *has* user plugins, and fall
back to the newest that merely exists, letting the caller tell the two
apart via :attr:`SourceChoice.has_plugins`.

No ``bpy`` import — unit-testable outside Blender.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import discovery
from .enumerate import PluginInfo, list_user_plugins


@dataclass(frozen=True)
class SourceChoice:
    """The Blender install chosen as the import source."""

    version: str
    path: Path
    plugins: list[PluginInfo] = field(default_factory=list)

    @property
    def has_plugins(self) -> bool:
        return bool(self.plugins)


def select_source(bases: list[Path] | None = None, **kwargs) -> SourceChoice | None:
    """Choose the best Blender install to import from.

    Returns ``None`` only when no Blender config dir exists at all — that
    is the genuine "no Blender installed" case. A returned choice with
    ``has_plugins == False`` means Blender is installed but has nothing
    the user could import.

    ``bases`` / ``**kwargs`` are forwarded to
    :func:`discovery.find_source_versions` so tests can pin the
    platform/home/env.
    """
    versions = discovery.find_source_versions(bases=bases, **kwargs)
    if not versions:
        return None

    # find_source_versions() is already newest-first, so the first hit is
    # the newest version that has anything to offer.
    for version, path in versions:
        plugins = list_user_plugins(path)
        if plugins:
            return SourceChoice(version, path, plugins)

    # Blender is installed, but no version has user plugins. Report the
    # newest so the UI can name a concrete version.
    version, path = versions[0]
    return SourceChoice(version, path, [])


def has_importable_plugins(bases: list[Path] | None = None, **kwargs) -> bool:
    """True when at least one installed Blender has user plugins to import."""
    choice = select_source(bases=bases, **kwargs)
    return choice is not None and choice.has_plugins
