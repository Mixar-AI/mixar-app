#!/bin/bash
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

# Initialize submodule to the exact commit specified by parent repo
echo "Initializing Blender submodule..."
GIT_LFS_SKIP_SMUDGE=1 git submodule update --init --recursive --force --progress

cd upstream
# Download LFS files using make update
if ! make update; then
    echo "Try running 'make update' manually in the upstream directory to download LFS files"
    echo "If you see 'command not found' errors for python3.11, run:"
    echo "  cd upstream/lib/macos_arm64 && git lfs pull"
fi
git lfs pull
cd ..
echo "Initialization complete!"

