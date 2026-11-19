<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-2.0-or-later -->

# Blender 5.3 UI review

The native macOS comparison reproduced an island that showed its glass bed but lost every control. Blender's framebuffer capture still showed the controls, so buffer-only review missed the defect. Preserving region alpha for Agent Bubble during window composition restores the native content. Other editors keep upstream's opaque alpha mask.

| Native capture | Result |
| --- | --- |
| [Mac before](mac-native-before.png) | Glass-only island: controls missing. |
| [Mac after](mac-native-after.png) | Tabs, transcript, focused charcoal composer and footer controls visible. |
| [Linux OpenGL after](linux-opengl-after.png) | Dark backdrop and focused charcoal composer intact; backdrop transparency was not measured. |

UI-only review covered empty and populated focused/idle composers, expanded steps, 3D/Image/Video/Splats/Library/Queue tabs, Zen/Moodboard/Engine/Texturing chrome, and File/Edit menus. Seventeen fixed-build buffer captures on Mac and seventeen native desktop captures on Linux were visually reviewed; Mac additionally used native OS captures for the island and pill. No paid provider requests were made. A matched 5.2 Engine view has the same dense grid pattern, so that is not introduced by this upgrade.

The Mac comparison used the preserved 5.2 app, the original 5.3 app and the rebuilt alpha fix. Linux used a private 5.3 checkout rebuilt with the same alpha fix, an isolated profile and a dedicated display; shared 5.2 builds and other sandboxes were not modified. Both native builds and 37 focused glass/lifecycle tests passed.

## Limits

- Linux OpenGL UI is reviewed. The sandbox initially lacked the NVIDIA Vulkan manifest and fell back to OpenGL. With a private manifest, Vulkan initialized on NVIDIA L4 but `vkCreateSwapchainKHR` returned `VK_ERROR_UNKNOWN` on Xvfb and native captures were black. Vulkan UI is **not approved** by this run.
- Texturing controls were reviewed while its viewport compiled shaders; this pass does not re-certify rendering or the functional workflows already tested.
- Windows was left to the user's separate machine. This run does not approve Windows or the full release.
- Detailed state, screenshots and build logs remain in the local ignored `build/qa/blender53-ui/` directory. The staged replay is `tests/qa/blender53_visual_ui_e2e.py`; native OS screenshots remain required.
