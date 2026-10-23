#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Compare the desktop QA source lights with its actual downloaded GLB.

Usage: python3 web_publish_lighting_audit.py source.json published.glb
Writes JSON to stdout and exits nonzero when an authored light is lost or
its physical intensity/color changes. This checks light transport only;
the native reference and browser screenshots still need visual review.
"""
import json
import math
import struct
import sys
from pathlib import Path


def audit(source, gltf):
    lights = gltf.get('extensions', {}).get('KHR_lights_punctual', {}).get('lights', [])
    exported = {}
    for node in gltf.get('nodes', []):
        index = node.get('extensions', {}).get('KHR_lights_punctual', {}).get('light')
        if index is not None:
            exported[node.get('name')] = lights[index]
    failures = []
    for light in source['lights']:
        actual = exported.get(light['name'])
        if actual is None:
            failures.append(f"Missing authored {light['type']} light: {light['name']}")
            continue
        expected_type = {'SUN': 'directional', 'POINT': 'point', 'SPOT': 'spot'}.get(light['type'])
        expected_intensity = light['energy'] * 683
        if light['type'] in ('POINT', 'SPOT'):
            expected_intensity /= 4 * math.pi
        if actual['type'] != expected_type or not math.isclose(actual.get('intensity', 1), expected_intensity, rel_tol=1e-5):
            failures.append(f"Changed type/intensity: {light['name']}")
        if any(not math.isclose(a, b, abs_tol=1e-5) for a, b in zip(actual.get('color', [1, 1, 1]), light['color'])):
            failures.append(f"Changed color: {light['name']}")
    return {
        'passed': not failures,
        'scope': 'authored light transport; not complete visual fidelity',
        'source_light_count': len(source['lights']),
        'exported_light_count': len(exported),
        'failures': failures,
        'source_world': source.get('world'),
        'source_view_transform': source.get('view_transform'),
        'extensions_used': gltf.get('extensionsUsed', []),
    }


def main():
    source = json.loads(Path(sys.argv[1]).read_text())
    data = Path(sys.argv[2]).read_bytes()
    magic, version, length = struct.unpack_from('<4sII', data)
    assert (magic, version, length) == (b'glTF', 2, len(data)), 'Invalid GLB header'
    size, kind = struct.unpack_from('<II', data, 12)
    assert kind == 0x4E4F534A, 'Missing JSON chunk'
    result = audit(source, json.loads(data[20:20 + size]))
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
