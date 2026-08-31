#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Generate config/mixar.json for the runtime bundle from environment variables.

Called by build.sh / build.bat during the build step.
All values come from env vars with sensible hardcoded defaults.

Usage:
    python3 scripts/generate_config.py --output <path>/mixar.json
    python3 scripts/generate_config.py --output <path>/mixar.json --version-file VERSION
"""

import argparse
import json
import os
import sys


def _read_version(version_file: str) -> str:
    """Read version string from the VERSION file."""
    try:
        with open(version_file, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        print(f"Warning: VERSION file not found at {version_file}, using 0.0.0")
        return "0.0.0"


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key, "").lower()
    if val in ("true", "1", "yes"):
        return True
    if val in ("false", "0", "no", ""):
        return default
    return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, "") or default)
    except ValueError:
        return default


def generate_config(version_file: str) -> dict:
    """Build the config dict from environment variables + hardcoded defaults.

    The ``dev_bypass`` block is only emitted for ``MIXAR_ENV=Dev`` builds.
    For any other environment, having ``DEV_BYPASS_*`` set in the build
    environment is treated as a configuration error and aborts the build —
    this is the C4 guard against accidentally shipping plaintext credentials
    inside the runtime bundle.
    """

    version = _env("MIXAR_VERSION") or _read_version(version_file)
    environment = _env("MIXAR_ENV", "Prod")

    bypass_enabled = _env_bool("DEV_BYPASS_ENABLED", False)
    bypass_username = _env("DEV_BYPASS_USERNAME")
    bypass_password = _env("DEV_BYPASS_PASSWORD")
    bypass_any_set = bypass_enabled or bool(bypass_username) or bool(bypass_password)

    if environment != "Dev" and bypass_any_set:
        sys.stderr.write(
            "ERROR: DEV_BYPASS_* environment variables are set but MIXAR_ENV="
            f"{environment!r}. Dev bypass is only permitted in Dev builds. "
            "Unset DEV_BYPASS_ENABLED / DEV_BYPASS_USERNAME / DEV_BYPASS_PASSWORD "
            "or build with MIXAR_ENV=Dev.\n"
        )
        sys.exit(1)

    config = {
        "environment": environment,
        "log_level": _env("MIXAR_LOG_LEVEL", "INFO"),
        "backend_url": _env("MIXAR_BACKEND_URL", "https://api.mixar.app"),
        "frontend_url": _env("MIXAR_FRONTEND_URL", "https://www.mixar.app"),
        "app_info": {
            "version": version,
        },
        "performance": {
            "ui_batch_budget_ms": 4,
        },
        # Update behaviour. Every key has a code-side default, so an older
        # mixar.json still works; these make the values visible and
        # overridable per build/environment.
        "updates": {
            "channel": _env("MIXAR_UPDATE_CHANNEL", "stable"),
            "check_delay_seconds": _env_int("MIXAR_UPDATE_CHECK_DELAY_S", 5),
            # Stage the installer as soon as an update is found, so
            # "Restart & Update" is instant rather than a download the user
            # waits through. Set false to keep the browser-download flow.
            "auto_download": _env_bool("MIXAR_UPDATE_AUTO_DOWNLOAD", True),
        },
    }

    if environment == "Dev":
        config["dev_bypass"] = {
            "enabled": bypass_enabled,
            "username": bypass_username,
            "password": bypass_password,
        }

    return config


def main():
    parser = argparse.ArgumentParser(
        description="Generate mixar.json for the runtime bundle"
    )
    parser.add_argument(
        "--output", required=True, help="Output path for mixar.json"
    )
    parser.add_argument(
        "--version-file",
        default=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "VERSION",
        ),
        help="Path to VERSION file (default: <repo>/VERSION)",
    )
    args = parser.parse_args()

    config = generate_config(args.version_file)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(config, f, indent=2)

    print(f"Generated {args.output}")
    print(f"  environment:  {config['environment']}")
    print(f"  version:      {config['app_info']['version']}")
    print(f"  backend_url:  {config['backend_url']}")
    print(f"  frontend_url: {config['frontend_url']}")


if __name__ == "__main__":
    main()
