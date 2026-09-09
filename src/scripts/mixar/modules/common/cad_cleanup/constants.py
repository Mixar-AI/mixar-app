# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

SCHEMA_VERSION = 1
STATE_KEY = '_mixar_cad_cleanup_v1'
OBJECT_KEY = '_mixar_cad_object_id'
OWNER_KEY = '_mixar_cad_run'
MAX_PAGE = 100
MAX_DECISIONS = 1000
VIEWS = {'front': (-1, 0, 0), 'rear': (1, 0, 0), 'left': (0, -1, 0),
         'right': (0, 1, 0), 'top': (0, 0, 1), 'bottom': (0, 0, -1),
         'perspective': (-1, -1, .7)}
