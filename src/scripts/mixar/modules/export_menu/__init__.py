# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Export sheet: the Zen toolbar's Export button opens one centred,
Spline-style dialog over a blurred window instead of the stock File ▸
Export list.

Format tiles on the left (3D files, game engines and the web, image and
video), the picked format's file name, quality and settings on the right,
and one Export action. Every format runs a pipeline that already exists:
3D files go through the agent export lane (``agent_export.export_to_path``:
presets, verification, privacy stripping), ``.blend`` / ``.mixar`` are copy
saves, images and videos are ``scene_render`` jobs delivered to a file, and
Web is Publish to Web. ``File ▸ Export`` keeps the stock menu.
"""
