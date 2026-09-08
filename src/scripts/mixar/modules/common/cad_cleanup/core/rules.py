# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Pure name evidence. Conflicting evidence never silently chooses a winner."""
import json
import re
from pathlib import Path

PROFILE = json.loads((Path(__file__).parents[1] / 'profile.json').read_text())
ALIASES = {'OTR': 'OUTER', 'INR': 'INNER', 'BMPR': 'BUMPER', 'FDR': 'FENDER',
           'FR': 'FRONT', 'RR': 'REAR', 'STRG': 'STEERING', 'ENG': 'ENGINE',
           'RAD': 'RADIATOR', 'SUSP': 'SUSPENSION', 'SCR': 'SCREW',
           'HARN': 'HARNESS', 'SPKR': 'SPEAKER', 'SEN': 'SENSOR', 'WDW': 'WINDOW',
           'FRT':'FRONT', 'GRILLE':'GRILL', 'SCRWS':'SCREW', 'LWR':'LOWER'}


def normalize(text):
    # Known CAD concatenation only; do not substring-match arbitrary part IDs.
    text = re.sub(r'(?i)\bPneuNu(?=PRV?\d)', 'PNEU NU ', text)
    tokens = re.findall(r'[A-Z0-9]+', text.upper())
    return ' '.join(ALIASES.get(t, t) for t in tokens)


def has(text, phrase):
    return (' ' + normalize(phrase) + ' ') in (' ' + text + ' ')


def parse_name(name):
    leaf = re.split(r'[\\/]', name)[-1].strip()
    leaf = re.sub(r'\.\d{3,}$', '', leaf)
    clean = re.sub(r'^(?:Copy \(\d+\) of |Result of )', '', leaf, flags=re.I)
    match = re.match(r'^([A-Z0-9-]+)[_ ](\d{2,4})[_ ](.+)', clean, re.I)
    descriptor = match.group(3) if match else clean
    descriptor = re.split(r'_(?:FROZEN|VALIDATED)(?:\b|_|#)|[\(#]', descriptor,
                          maxsplit=1, flags=re.I)[0]
    part_id = bool(re.search(r'(?<![A-Z0-9])[A-Z]{0,4}\d{6,}[A-Z0-9-]*', clean, re.I))
    if match and len(match.group(1).replace('-', '')) >= 8:
        part_id = True
    return {'leaf': leaf, 'descriptor': normalize(descriptor),
            'part_id': part_id, 'released': bool(part_id and match),
            'protected': part_id, 'assembly': name[:-len(leaf)] if leaf else ''}


def decision(category, reason, evidence=(), confidence='high'):
    return {'category': category, 'reason': reason, 'evidence': list(evidence),
            'confidence': confidence}


def classify(record):
    parsed = parse_name(record['name'])
    text = parsed['descriptor']
    if not text or re.fullmatch(r'(BODY|PARTBODY|PRODUCT\d*|PART\d*|MSBR\d*|SOLID)\d*', text):
        return decision('_REVIEW_ANONYMOUS', 'No semantic descriptor', confidence='low')
    # Complete phrases resolve known ambiguities without substring collisions.
    specific = [('STEERING WHEEL', '_SYS_STEERING_MAIN'),
                ('SPARE WHEEL CARRIER', '_SYS_BODY_STRUCT_REINF_BRKT'),
                ('WHEELHOUSE', '_SYS_BODY_STRUCT_MAIN'),
                ('WHEEL HOUSE', '_SYS_BODY_STRUCT_MAIN'),
                ('WHEEL ARCH', '_SYS_BODY_STRUCT_MAIN'),
                ('RADIATOR GRILL', '_VIZ_RADIATOR_GRILL_MAIN'),
                ('FRONT BUMPER LOWER GRILL', '_VIZ_RADIATOR_GRILL_MAIN'),
                ('RADIATOR CROSS MEMBER', '_SYS_BODY_STRUCT_REINF_BRKT'),
                ('HEADLINER', '_SYS_INTERIOR_COVER_TRIM'),
                ('DAYLIGHT SENSOR', '_SYS_ELECTRICAL_MAIN'),
                ('FUEL FILLER LID', '_SYS_FUEL_COVER_TRIM'),
                ('SHOCK ABS', '_SYS_SUSPENSION_MAIN'),
                ('VALVE SPRING', '_SYS_ENGINE_MECHANISM'),
                ('SPRING VALVE', '_SYS_ENGINE_MECHANISM'),
                ('OIL COOLER', '_SYS_COOLING_MAIN')]
    matches = [(p, c) for p, c in specific if has(text, p)]
    if matches:
        cats = {c for _, c in matches}
        residue = text
        for phrase, _ in matches:
            residue = (' ' + residue + ' ').replace(' ' + normalize(phrase) + ' ', ' ').strip()
        competing = ('LAMP', 'SENSOR', 'BRAKE', 'FUEL', 'SEAT', 'HARNESS', 'AIRBAG')
        conflicts = [w for w in competing if has(residue, w)]
        if len(cats) > 1 or conflicts:
            return decision('_REVIEW_CONFLICT', 'Conflicting specific phrases', matches, 'low')
        return decision(matches[0][1], 'Specific component phrase', [matches[0][0]])
    part_type = 'MAIN'
    # Part type belongs to the descriptor head, never inside DESCRIPTION etc.
    for kind, words in PROFILE['SYS_TYPES']:
        if any(text == normalize(w) or text.startswith(normalize(w) + ' ') for w in words):
            part_type = kind
            break
    if has(text, 'DOOR'):
        front, rear = has(text, 'FRONT'), has(text, 'REAR')
        if front and rear:
            return decision('_REVIEW_CONFLICT', 'Both front and rear door evidence', confidence='low')
        group = 'FR_DOOR' if front else 'RR_DOOR' if rear else 'DOOR'
        if has(text, 'GLASS'): part_type = 'GLASS'
        elif has(text, 'OUTER') and has(text, 'PANEL'): part_type = 'OUTER_PANEL'
        elif has(text, 'INNER') and has(text, 'PANEL'): part_type = 'INNER_PANEL'
        elif has(text, 'OUTER') and has(text, 'HANDLE'): part_type = 'EXT_HANDLE'
        elif any(has(text, k) for k in ('AIRBAG', 'SENSOR', 'HARNESS', 'MOTOR')):
            part_type = 'ELECTRICAL'
        return decision('_VIZ_' + group + '_' + part_type, 'Door descriptor', [text])
    candidates = {}
    for group, words in PROFILE['SUBSYS']:
        for w in words:
            if has(text, w): candidates['_VIZ_' + group] = w
    extra = {'ENGINE': ('ENGINE', 'VALVE'), 'COOLING': ('RADIATOR', 'COOLER', 'COOLANT'),
             'SUSPENSION': ('SUSPENSION',), 'INTERIOR': ('HEADLINER',),
             'ELECTRICAL': ('SENSOR', 'HARNESS', 'SPEAKER'),
             'BODY_STRUCT': ('BODY SIDE', 'WHEELHOUSE')}
    # Generic type tokens cannot establish a system, nor can supplier IDs.
    generic = {'PANEL', 'EXT', 'REINF', 'UNIT', 'ARM', 'LINK', 'SPR', 'SPRING', 'CROSS', 'POIGNEE'}
    for system, words in PROFILE['SYSTEM']:
        for w in list(words) + list(extra.get(system, ())):
            if w not in generic and has(text, w): candidates['_SYS_' + system] = w
    # A lamp descriptor belongs to the exterior lamp group, not generic electrical.
    if '_VIZ_LAMPS' in candidates and candidates.get('_SYS_ELECTRICAL') == 'LAMP':
        candidates.pop('_SYS_ELECTRICAL')
    if len(candidates) > 1:
        return decision('_REVIEW_CONFLICT', 'Multiple systems match; inspect before assigning',
                        sorted(candidates.items()), 'low')
    if not candidates:
        return decision('_REVIEW_UNCLASSIFIED', 'Insufficient system evidence', [text], 'low')
    group, evidence = next(iter(candidates.items()))
    return decision(group + '_' + part_type, 'Token-bounded descriptor evidence', [evidence])


def cull_evidence(record, secondary=False):
    parsed = parse_name(record['name'])
    words = PROFILE['CULL_KEYWORDS_2' if secondary else 'CULL_KEYWORDS']
    matches = [w for w in words if has(parsed['descriptor'], w)]
    if matches:
        return decision('_REVIEW_CULL', 'Construction-name evidence needs inspection; never auto-delete',
                        matches, 'low')
    return None
