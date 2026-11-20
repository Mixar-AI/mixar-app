# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Install bundled dependencies only when the existing wheel set needs repair.

Windows cannot delete a loaded .pyd. The app's MCP relay can keep cryptography's
_rust.pyd loaded while a developer rebuilds, so pip's unconditional --upgrade
--target pass would fail even when every installed dependency is already valid.
"""

import importlib.metadata
import base64
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.utils import canonicalize_name
from pip._vendor.packaging.version import Version


def _prune_stale_metadata(site_packages):
    """pip --target leaves old dist-info directories after a version upgrade."""
    root = site_packages.resolve()
    by_name = {}
    for path in root.glob("*.dist-info"):
        try:
            distribution = importlib.metadata.PathDistribution(path)
            name = canonicalize_name(distribution.metadata["Name"])
            version = Version(distribution.version)
        except (KeyError, TypeError, ValueError, OSError):
            continue
        by_name.setdefault(name, []).append((version, path, distribution))

    for candidates in by_name.values():
        if len(candidates) < 2:
            continue
        version, newest, distribution = max(candidates, key=lambda item: item[0])
        files = distribution.files
        if not files or any(not distribution.locate_file(file).is_file() for file in files):
            continue
        for old_version, old, _ in candidates:
            if old_version >= version:
                continue
            resolved = old.resolve()
            if resolved.parent != root or not resolved.name.endswith(".dist-info"):
                raise ValueError(f"Refusing to remove metadata outside site-packages: {old}")
            shutil.rmtree(resolved)
            print(f"Removed stale wheel metadata: {old.name}")


def _required_distributions(requirements_file):
    requirements = []
    for line in requirements_file.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        requirement = Requirement(line)
        if requirement.url:
            return None  # A direct URL could change without its version changing.
        if requirement.marker is None or requirement.marker.evaluate():
            requirements.append(requirement)
    return requirements


def _wheel_files_match(distribution):
    files = distribution.files
    if not files:
        return False
    for file in files:
        path = distribution.locate_file(file)
        if not path.is_file() or (file.size is not None and path.stat().st_size != file.size):
            return False
        if file.hash is not None:
            digest = hashlib.new(file.hash.mode)
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            if base64.urlsafe_b64encode(digest.digest()).rstrip(b"=").decode("ascii") != file.hash.value:
                return False
    return True


def _installed_and_complete(requirements_file):
    """Return (metadata_is_compatible, distributions_with_changed_files)."""
    try:
        requirements = _required_distributions(requirements_file)
        if requirements is None:
            return False, []
        pending = [(requirement, {""}) for requirement in requirements]
        visited = set()
        modified = {}
        while pending:
            requirement, parent_extras = pending.pop()
            if requirement.marker and not any(
                requirement.marker.evaluate({"extra": extra}) for extra in parent_extras
            ):
                continue
            key = (canonicalize_name(requirement.name), tuple(sorted(requirement.extras)))
            if key in visited:
                continue
            visited.add(key)
            distribution = importlib.metadata.distribution(requirement.name)
            if distribution.version not in requirement.specifier:
                return False, []
            if not _wheel_files_match(distribution):
                modified[canonicalize_name(distribution.metadata["Name"])] = distribution.version
            pending.extend(
                (Requirement(text), requirement.extras or {""})
                for text in (distribution.requires or ())
            )
    except (ValueError, importlib.metadata.PackageNotFoundError, OSError):
        return False, []

    compatible = subprocess.run(
        [sys.executable, "-s", "-B", "-m", "pip", "check"],
        check=False,
    ).returncode == 0
    return compatible, modified


def main():
    requirements_file = Path(sys.argv[1])
    site_packages = Path(sys.argv[2])
    _prune_stale_metadata(site_packages)
    compatible, modified = _installed_and_complete(requirements_file)
    if compatible and not modified:
        print("Bundled Python requirements are complete; skipping pip upgrade")
        return 0

    command = [sys.executable, "-s", "-B", "-m", "pip", "install", "--upgrade",
               "--no-compile", "--target", str(site_packages)]
    if compatible:
        print("Repairing changed bundled wheels: " + ", ".join(sorted(modified)))
        command.extend(["--no-deps", *(f"{name}=={version}" for name, version in sorted(modified.items()))])
    else:
        command.extend(["-r", str(requirements_file)])
    result = subprocess.run(command, check=False)
    if result.returncode:
        print(
            "Python package installation failed. On Windows, close Mixar and "
            "any MCP clients using this build, then rerun make build. "
            "A running process can lock native .pyd files.",
            file=sys.stderr,
        )
        return result.returncode
    _prune_stale_metadata(site_packages)
    if _installed_and_complete(requirements_file) != (True, {}):
        print("Python package installation did not produce a complete dependency set", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
