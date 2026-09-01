# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fake WindowManager / Window / Area / Region objects for agent_ui tests.

The driver reads geometry from ``WindowManager.mixar_qa_ui_dump`` (JSON) and
the bpy window tree, and injects input through ``Window.event_simulate`` /
``Window.cursor_warp``. These fakes record every injected event so tests can
assert the exact sequence without a running Blender.
"""

import json
import types


class FakeRegion:
    def __init__(self, ptr, rtype, x, y, width, height):
        self._ptr = ptr
        self.type = rtype
        self.x, self.y, self.width, self.height = x, y, width, height

    def as_pointer(self):
        return self._ptr


class FakeArea:
    def __init__(self, ptr, atype, x, y, width, height, regions=()):
        self._ptr = ptr
        self.type = atype
        self.x, self.y, self.width, self.height = x, y, width, height
        self.regions = list(regions)
        self.redraws = 0

    def as_pointer(self):
        return self._ptr

    def tag_redraw(self):
        self.redraws += 1


class FakeScene:
    def __init__(self):
        self.mixie_chat_state = "BUSY"
        self.mixie_chat_is_busy = True


class FakeWindow:
    def __init__(self, ptr, areas, width=1600, height=1000):
        self._ptr = ptr
        self.screen = types.SimpleNamespace(areas=list(areas))
        self.global_areas = []
        self.width, self.height = width, height
        self.scene = FakeScene()
        self.events = []
        self.warps = []
        self.drops = []

    def as_pointer(self):
        return self._ptr

    def event_simulate(self, **kw):
        self.events.append(kw)

    def cursor_warp(self, x, y):
        self.warps.append((x, y))

    def mixar_qa_drop_file(self, filepath, x, y):
        self.drops.append((filepath, x, y))


class FakeWM:
    """``props`` lists the RNA properties this build exposes (the fork's
    mixed-mode bools are absent on builds without the C++ change)."""

    def __init__(self, windows, widgets, props=()):
        self.windows = list(windows)
        self._widgets = widgets
        self.bl_rna = types.SimpleNamespace(properties=set(props))
        for name in props:
            setattr(self, name, False)
        self.mixie_chat_is_logged_in = True

    @property
    def mixar_qa_ui_dump(self):
        return json.dumps({"widgets": [dict(w) for w in self._widgets]})


def widget(win, area, region, text="", rect=(0, 0, 100, 20), **extra):
    """One raw dump entry as the C++ inspector emits it."""
    w = {
        "w": win.as_pointer(),
        "a": area.as_pointer() if area is not None else 0,
        "r": region.as_pointer() if region is not None else 0,
        "at": 0, "rt": 0,
        "type": extra.pop("type", "Pushbutton"),
        "text": text, "tip": extra.pop("tip", ""),
        "rect": list(rect), "enabled": extra.pop("enabled", True),
        "sel": extra.pop("sel", False), "popup": extra.pop("popup", False),
    }
    w.update(extra)
    return w


def simple_layout(props=()):
    """One window, one MIXIE area with a UI sidebar region floating over the
    WINDOW region on the right; returns (wm, win, area, ui_region, win_region)."""
    win_region = FakeRegion(101, "WINDOW", 0, 0, 1000, 800)
    ui_region = FakeRegion(102, "UI", 700, 0, 300, 800)
    area = FakeArea(11, "MIXIE", 0, 0, 1000, 800, regions=[win_region, ui_region])
    top = FakeArea(12, "TOPBAR", 0, 800, 1000, 40,
                   regions=[FakeRegion(103, "WINDOW", 0, 800, 1000, 40)])
    win = FakeWindow(1, [area, top])
    widgets = []
    wm = FakeWM([win], widgets, props=props)
    return wm, win, area, ui_region, win_region, widgets
