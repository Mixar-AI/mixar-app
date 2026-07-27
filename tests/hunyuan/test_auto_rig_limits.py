# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Auto Rig upload contract regression coverage."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.hunyuan.constants import MAX_FILE_SIZE_ANIMATE_RIG


def test_auto_rig_limit_matches_backend_150_mb_contract():
    assert MAX_FILE_SIZE_ANIMATE_RIG == 150 * 1024 * 1024
