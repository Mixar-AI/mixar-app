# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

SCHEMA_VERSION = 1
STATE_KEY = '_mixar_cad_cleanup_v1'
OBJECT_KEY = '_mixar_cad_object_id'
OWNER_KEY = '_mixar_cad_run'
STAGES = ('1', '2', '3', '4', '5', '5b', '6', '7', '8', '8b', '9', '10')
GROUPS = ('01_IDENTIFIED', '02_NOT_NEEDED', '03_NEEDS_REVIEW')
MAX_PAGE = 100
MAX_DECISIONS = 1000
VIEWS = {'front': (-1, 0, 0), 'rear': (1, 0, 0), 'left': (0, -1, 0),
         'right': (0, 1, 0), 'top': (0, 0, 1), 'bottom': (0, 0, -1),
         'perspective': (-1, -1, .7)}
SYSTEMS = ('ENGINE', 'COOLING', 'HVAC', 'EXHAUST', 'FUEL', 'BRAKES',
           'SUSPENSION', 'STEERING', 'ELECTRICAL', 'INTERIOR', 'SEATS', 'BODY_STRUCT')
EXTERIORS = ('FR_DOOR', 'RR_DOOR', 'DOOR', 'BUMPER', 'HOOD', 'TAILGATE', 'ROOF',
             'FENDER', 'LAMPS', 'MIRROR', 'GLAZING', 'WHEELS', 'LOGO_BADGE',
             'COWL', 'RADIATOR_GRILL')
TYPES = ('MAIN', 'FASTENERS', 'SEALS_FOAM', 'HOSE_TUBE', 'REINF_BRKT', 'COVER_TRIM',
         'MECHANISM', 'OUTER_PANEL', 'INNER_PANEL', 'GLASS', 'EXT_HANDLE',
         'TRIM_INTERIOR', 'ELECTRICAL')
REVIEW_CATEGORIES = ('_REVIEW_UNCLASSIFIED', '_REVIEW_CONFLICT', '_REVIEW_ANONYMOUS',
                     '_REVIEW_GEOMETRY', '_REVIEW_UNITS', '_REVIEW_CULL',
                     '_REVIEW_SIZE', '_REVIEW_UNSUPPORTED')
CATEGORIES = tuple('_SYS_' + s + '_' + t for s in SYSTEMS for t in TYPES) + tuple(
    '_VIZ_' + s + '_' + t for s in EXTERIORS for t in TYPES) + REVIEW_CATEGORIES + (
    '_TRIAGE_NONGEOMETRY', '_Cull_CONFIRMED', '_DUP_COINCIDENT')
