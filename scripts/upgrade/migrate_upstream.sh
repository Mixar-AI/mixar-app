#!/bin/bash
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

# Unix wrapper script for migrate_upstream.py
# Orchestrates the complete upstream migration workflow

set -euo pipefail

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Call the Python script with all arguments
python3 "$SCRIPT_DIR/migrate_upstream.py" "$@"
