# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Export card: the topbar Export button's sheet.

One card for every way out of Mixar — a project copy (.mixar / .blend), a 3D
file (glTF/GLB, FBX, USD/USDZ, OBJ, STL), a rendered image or video, or
Publish to Web — chosen from a sidebar of app-icon tiles, with the target's
settings and the destination on the right and one Export button.

The card only decides and draws; the work goes to the lanes that already
own it: the shared export lane (`space_mixie_chat/core/agent_export`) for 3D
files, a copy save for projects, `scene_render` for background renders and
`web_publish` for the web. Settings live on ``WindowManager.mixar_export_card``.
"""
