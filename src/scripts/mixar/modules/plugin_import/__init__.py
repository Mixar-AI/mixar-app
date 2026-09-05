# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Plugin Import.

One-click import of a user's existing *vanilla Blender* plugins into
Mixar. Mixar is a Blender 5.0 fork with a rebranded on-disk identity
(user data under ``Mixar/5.0/``), so a normal Blender install lives
side-by-side under ``Blender/<ver>/`` and can be read as an import
source.

Scope (see CLAUDE.md module table):
- Reads only the *user config* tree of the newest installed Blender
  version, so plugins bundled with Blender itself are excluded — those
  already ship inside Mixar as part of the fork.
- Handles both legacy add-ons (``scripts/addons``) and the 4.2+
  extensions system (``extensions/<repo>/<pkg>``).
- Files are always copied in; the user picks which imported plugins to
  *enable* via a checklist (default all on).
"""
