# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Regression coverage for Windows wheel metadata and loaded native modules."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/windows/install_python_requirements.py"
spec = importlib.util.spec_from_file_location("install_python_requirements", SCRIPT)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def _wheel(root, name, version):
    package = root / name
    package.mkdir(exist_ok=True)
    (package / "__init__.py").write_text("\n", encoding="utf-8")
    metadata = root / f"{name}-{version}.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        encoding="utf-8",
    )
    (metadata / "RECORD").write_text(
        f"{name}/__init__.py,,\n{name}-{version}.dist-info/METADATA,,\n"
        f"{name}-{version}.dist-info/RECORD,,\n",
        encoding="utf-8",
    )
    return metadata


class WindowsRequirementsInstallTest(unittest.TestCase):
    def test_prunes_only_old_metadata_from_complete_new_wheel(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = _wheel(root, "sample", "1.0")
            new = _wheel(root, "sample", "2.0")
            installer._prune_stale_metadata(root)
            self.assertFalse(old.exists())
            self.assertTrue(new.exists())
            self.assertTrue((root / "sample/__init__.py").exists())

    def test_keeps_old_metadata_when_new_wheel_is_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = _wheel(root, "sample", "1.0")
            new = _wheel(root, "sample", "2.0")
            (new / "RECORD").write_text("missing.py,,\n", encoding="utf-8")
            installer._prune_stale_metadata(root)
            self.assertTrue(old.exists())
            self.assertTrue(new.exists())

    def test_healthy_install_never_calls_pip_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requirements = root / "requirements.txt"
            requirements.write_text("sample>=1\n", encoding="utf-8")
            site_packages = root / "site-packages"
            site_packages.mkdir()
            with mock.patch.object(installer, "_installed_and_complete", return_value=(True, {})), \
                 mock.patch.object(installer.subprocess, "run", side_effect=AssertionError("pip ran")), \
                 mock.patch.object(sys, "argv", [str(SCRIPT), str(requirements), str(site_packages)]):
                self.assertEqual(installer.main(), 0)

    def test_detects_upstream_file_replaced_after_pip_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata = _wheel(root, "sample", "2.0")
            package_file = root / "sample/__init__.py"
            import base64
            import hashlib
            digest = base64.urlsafe_b64encode(hashlib.sha256(b"new\n").digest()).rstrip(b"=").decode()
            (metadata / "RECORD").write_text(
                f"sample/__init__.py,sha256={digest},4\n"
                f"sample-2.0.dist-info/METADATA,,\n"
                f"sample-2.0.dist-info/RECORD,,\n",
                encoding="utf-8",
            )
            distribution = installer.importlib.metadata.PathDistribution(metadata)
            package_file.write_bytes(b"old\n")
            self.assertFalse(installer._wheel_files_match(distribution))
            package_file.write_bytes(b"new\n")
            self.assertTrue(installer._wheel_files_match(distribution))

    def test_repairs_changed_wheel_without_replacing_other_native_wheels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requirements = root / "requirements.txt"
            requirements.write_text("typing-extensions>=4\ncryptography>=42\n", encoding="utf-8")
            site_packages = root / "site-packages"
            site_packages.mkdir()
            outcomes = [(True, {"typing-extensions": "4.16.0"}), (True, {})]
            with mock.patch.object(installer, "_installed_and_complete", side_effect=outcomes), \
                 mock.patch.object(installer.subprocess, "run", return_value=mock.Mock(returncode=0)) as run, \
                 mock.patch.object(sys, "argv", [str(SCRIPT), str(requirements), str(site_packages)]):
                self.assertEqual(installer.main(), 0)
            command = run.call_args.args[0]
            self.assertIn("--no-deps", command)
            self.assertIn("typing-extensions==4.16.0", command)
            self.assertFalse(any("cryptography" in argument for argument in command))


if __name__ == "__main__":
    unittest.main()
