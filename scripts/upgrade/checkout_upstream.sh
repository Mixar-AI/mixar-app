#!/bin/bash
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

# Unix wrapper script for checkout_upstream.py
# This script simply calls the Python implementation

set -euo pipefail

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Call the Python script with all arguments
python3 "$SCRIPT_DIR/checkout_upstream.py" "$@"
