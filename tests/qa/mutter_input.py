# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Scoped native input for GNOME QA, including XWayland compositor gestures.

Uses a local Mutter remote-desktop session and primary-monitor coordinate
mapping. No network server or clipboard access is enabled. Stop the session
in finally. Requires the system PyGObject package.
"""
import sys

sys.path.append('/usr/lib/python3/dist-packages')
from gi.repository import Gio, GLib


class MutterInput:
    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.desktop = 'org.gnome.Mutter.RemoteDesktop'
        self.cast = 'org.gnome.Mutter.ScreenCast'
        self.path = self.call(self.desktop, '/org/gnome/Mutter/RemoteDesktop',
                              self.desktop, 'CreateSession')[0]
        try:
            session_id = self.call(self.desktop, self.path, 'org.freedesktop.DBus.Properties',
                                   'Get', '(ss)', (self.desktop+'.Session', 'SessionId'))[0]
            cast_path = self.call(self.cast, '/org/gnome/Mutter/ScreenCast', self.cast,
                                  'CreateSession', '(a{sv})',
                                  ({'remote-desktop-session-id': GLib.Variant('s', session_id)},))[0]
            self.stream = self.call(self.cast, cast_path, self.cast+'.Session',
                                     'RecordMonitor', '(sa{sv})', ('', {}))[0]
            self.call(self.desktop, self.path, self.desktop+'.Session', 'Start')
        except BaseException:
            self.close()
            raise

    def call(self, dest, path, interface, method, signature=None, values=()):
        result = self.bus.call_sync(dest, path, interface, method,
                                    GLib.Variant(signature, values) if signature else None,
                                    None, Gio.DBusCallFlags.NONE, 10000, None)
        return result.unpack()

    def move(self, x, y):
        self.call(self.desktop, self.path, self.desktop+'.Session',
                  'NotifyPointerMotionAbsolute', '(sdd)', (self.stream, float(x), float(y)))

    def button(self, down, number=1):
        self.call(self.desktop, self.path, self.desktop+'.Session',
                  'NotifyPointerButton', '(ib)', ({1:272, 2:274, 3:273}[number], bool(down)))

    def key(self, keysym, down):
        self.call(self.desktop, self.path, self.desktop+'.Session',
                  'NotifyKeyboardKeysym', '(ub)', (keysym, bool(down)))

    def close(self):
        if self.path:
            self.call(self.desktop, self.path, self.desktop+'.Session', 'Stop')
            self.path = None
