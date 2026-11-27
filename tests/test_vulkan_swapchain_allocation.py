# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Keep Blender's layer compatibility fix when rebasing the GHOST overlay."""

import re
from pathlib import Path


def test_swapchain_images_are_allocated_at_creation():
    root = Path(__file__).resolve().parents[1]
    source = (root / "src/intern/ghost/intern/GHOST_ContextVK.cc").read_text()
    create = source.split("GHOST_TSuccess GHOST_ContextVK::recreateSwapchain(", 1)[1]
    create = create.split("device_vk.functions.vkCreateSwapchainKHR(", 1)[0]
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", create, flags=re.S)
    assert "VK_SWAPCHAIN_CREATE_DEFERRED_MEMORY_ALLOCATION_BIT_" not in code
