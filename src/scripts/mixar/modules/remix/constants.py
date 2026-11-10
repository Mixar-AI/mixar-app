# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Remix: open a copy of someone's published post or game, and credit it
when the copy is published (``mixar-play/docs/remix.md``)."""

# Scene ID property (a JSON string) naming what this project was remixed
# from: {"kind", "id", "slug", "title", "author": {"handle", "display_name"},
# "url"}. A plain ID property so ``--background`` processes read it too.
REMIX_PROP = "mixar_remixed_from"
REMIXES_SUBDIR = "mixar/remixes"
TITLE_SUFFIX = " (remix)"

# The inbox: how often the app asks the store for remixes started on the web.
# Fast right after launch (the app was probably opened by the web page's
# link), slow afterwards.
POLL_FIRST_S = 4.0
POLL_FAST_S = 10.0
POLL_FAST_WINDOW_S = 180.0
POLL_SLOW_S = 60.0

SOURCE_DIRNAME = ".remix_source"
SOURCE_TIMEOUT_S = 10 * 60.0
SOURCE_RESULT_SCHEMA = "mixar_remix_source_result_v1"
# Formats the store names in a remix package (``source.format``).
FORMAT_MIXAR, FORMAT_GLB, FORMAT_PACKAGE = "mixar", "glb", "game_package"
