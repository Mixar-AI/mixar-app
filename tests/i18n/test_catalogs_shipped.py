# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The shipped catalogs: one per Blender language, in step with mixar.pot,
placeholders intact, and the template current with the source."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "i18n"))

import check_catalogs  # noqa: E402
from i18n_common import default_upstream_dir, load_runtime_package  # noqa: E402


def test_catalogs_are_complete_and_valid(capsys):
    constants, po = load_runtime_package()
    if not (constants.LOCALE_DIR / constants.TEMPLATE_NAME).is_file():
        # mixar.pot is git-ignored: extract_messages.py writes it from the source
        # and the upstream checkout (make i18n_update / make i18n_check).
        pytest.skip("needs mixar.pot (run make i18n_update with the upstream checkout)")
    # Every language fully translated at merge time; a new UI string arrives
    # untranslated (English at runtime) and is reported, never silently lost.
    status = check_catalogs.check(constants, po, min_coverage=None, quiet=True)
    assert status == 0, capsys.readouterr().out


def test_template_is_current():
    if default_upstream_dir() is None:
        pytest.skip("needs the upstream Blender checkout (make init) to diff overrides")
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/i18n/extract_messages.py"), "--check"],
        capture_output=True, text=True, cwd=REPO,
    )
    assert result.returncode == 0, result.stdout + result.stderr
