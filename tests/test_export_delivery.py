# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

import json

from mixar.modules.space_mixie_chat.core.export_verify import verify_export
from mixar.modules.space_mixie_chat.core.export_verification_status import (
    verification_status, verification_warning,
)


def test_shared_mesh_nodes_are_not_missing_objects(tmp_path):
    doc = {'asset': {'version': '2.0'}, 'meshes': [{'primitives': []}],
           'nodes': [{'children': [1, 2]}, {'mesh': 0}, {'mesh': 0}, {'mesh': 0}],
           'scenes': [{'nodes': [0]}]}
    path = tmp_path / 'instances.gltf'
    path.write_text(json.dumps(doc))
    result = verify_export(str(path), 'gltf', {'mesh_count': 2})
    assert result['meshes'] == 1  # retain the existing definition count
    assert result['mesh_instances'] == 2  # ignore the orphan third instance
    assert result['passed'], result['issues']
    missing = verify_export(str(path), 'gltf', {'mesh_count': 3})
    assert not missing['passed']
    assert '2 mesh(es); 3 were expected' in missing['issues'][0]


def test_delivery_status_does_not_call_unchecked_output_verified():
    for verification in (None, {}, {'checked': False, 'passed': True}):
        assert verification_status(verification) == 'unverified'
        assert 'could not be fully verified' in verification_warning(verification)
    failed = {'checked': True, 'passed': False, 'issues': ['mismatch']}
    assert verification_status(failed) == 'verification_failed'
    assert 'Review verification.issues' in verification_warning(failed)
    passed = {'checked': True, 'passed': True}
    assert verification_status(passed) == 'verified'
    assert verification_warning(passed) == ''
