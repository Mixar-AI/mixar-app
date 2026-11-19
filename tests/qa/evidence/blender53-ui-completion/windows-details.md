<!-- SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited -->
<!-- SPDX-License-Identifier: GPL-2.0-or-later -->

# Windows supplemental UI verification

All ten final supplemental cases passed state checks and scoped visual review. The exact image ledger accounts for **687 final PNG paths / 603 distinct SHA256 contents, with zero unreviewed final images**. This supplements the earlier Windows auth, Codex, splat, OpenGL/Vulkan glass and lifecycle campaign; it does not replace or rerun that evidence.

The private Windows Server/Tesla T4 runtime was Mixar 4.4.7, Blender 5.3, Python 3.13.13, Vulkan, against UAT8. Eight broad cases used product `1a9e791e3b199af1016917a3e2fe37c7272b0212`; the two affected native-fix cases used `58b795ae6383329687d2fd95f7b80dc9a3ce17e4` (EXE SHA256 `bdce17142518b94dfa09c433b033aac24cd6becef38085398b4f29c8c61e928e`). Every run had a fresh disposable profile, memory keyring and credential-store guard. No provider turns or credit submissions were made.

| Final case | State time | Vision and evidence |
| --- | ---: | --- |
| Island tab alignment: widths 560/678/1100, UI 100/125% | PASS 15.88s | 38 PNG; `tabs-visual-review.json` |
| Image/Video fields, local references, tab state, Queue | PASS 10.92s | 18 PNG; `tabs-visual-review.json` |
| All eight tabs including Add-on, two scene draft/transcript restores | PASS 15.24s | 58 PNG; `alltabs-final-visual-review.json` |
| Moodboard drawer toolbar, hover, picker cancel, text placement/edit, local image, resize | PASS 30.56s | 48 PNG; `tools-direct-final-visual-review.json` |
| Four framed Moodboard templates and model/settings/Quality menus | PASS 24.34s | 91 PNG; `dropdowns-visual-review.json` |
| Empty/populated composer, Shift+Enter/Escape, Rules/Attach/outside, disconnected Enter | PASS 49.69s | 146 PNG; `ui11-final-visual-review.json` |
| Committed three-line idle draft, fresh 125% tooltip, Render Settings, Engine, compact Workspaces/Texturing/Layout | PASS 25.92s | 56 PNG; `workflow-final-visual-review.json` |
| Public Shift+M in Zen and Engine, pill, actual Window menu | PASS 4.86s | 26 PNG; `tools-direct-final-visual-review.json` |
| Parameter help in drawer and standalone host at 100/125%, toolbar visible | PASS 68.97s | 135 PNG; `help-final-visual-review.json` |
| Board edge overlap at 100/125/150%, normal Move→Rotate, grip, Engine edge resize/restore | PASS 27.38s | 71 PNG; `hit-final-visual-review.json` |

Earlier workflow evidence additionally proves transcript scroll/wrapping at widths 760/560, header scales 0.8–2 and File/Edit/Render menus: 115 PNG paths in `workflow-first-visual-review.json`. That whole attempt later failed a stale selector and is retained as partial evidence, not a complete case pass. Original failed attempts and the UI11 false-pass file-picker evidence remain preserved separately. The corrected UI11 replay clicks a real uncovered header and asserts no FILE_BROWSER; final screenshots confirm closure.

The expanded tests found a real inherited hit-routing bug: at 125%, the Moodboard Board button center `[486,413]` lay on the visible fixed Zen TOOLS right edge `486`; clicking it entered generic region resize instead of opening the menu. The relevant policy is byte-identical to develop's Blender 5.2 baseline, so this is not established as a newly introduced 5.3 regression. Commit `58b795ae6` removes the resize action zone only for the visible fixed floating Zen toolbar. The fixed replay opens the actual menu at all three overlapping scales; recorded Board-center/toolbar-edge pairs are `389/389`, `486/486`, `583/584`. Normal toolbar tools and Moodboard grip still work. Engine TOOLS right edge expands `391→461` and restores exactly to `391`. Help now passes with the toolbar visible and the diagnostic toolbar-hiding option disabled.

All 66 distinct hit-case contents were inspected through 17 indexed sheets and two additional full native originals; five duplicate files were SHA-verified. The help aggregate covers 134 distinct contents with original images/native-size sheets and pixel-identical desktop crops. All final cases include actual native composition captures. The final composer is neutral dark, tabs and controls remain sharp, and the tested menus are readable.

Preserved visual limitations: disconnected-Send notifications can be obscured behind the island at its default position (the notification layout/renderer matches the 5.2 source); a small unframed Moodboard card intentionally hides controls and has an unreadably small world-scaled hint, while real Frame Selected yields usable forms; some external left port labels meet the drawer edge; compact Texturing labels require truncation/scrolling. UI-scale testing on this single desktop does not certify physical high-DPI or multiple monitors. This report does not claim all historical diagnostic images were inspected: the aggregate has 1,760 total retained PNG paths, 1,184 reviewed or exact matches, and explicitly marks the remaining historical diagnostics unread.

Stall logs were recorded before and after the native-fix cases. Help: startup five stalls (maximum 1,416ms), replay zero. Hit replay: startup 13 stalls (maximum 3,211ms); replay four stalls—two screenshot instrumentation costs (210ms/159ms) and two first Engine Layout draw costs (964ms/174ms). The latter are observed drawing costs, not attributed to shader compilation without evidence; no claim of zero runtime stalls is made.

All ten final run summaries confirm the owned app stopped. Final cleanup at `2026-11-14T16:45:02Z` found zero owned application processes, removed only the eleven completed owned tasks, and retained evidence and old stashes. Shared Blender 5.2 source/upstream/library pins stayed unchanged. All four lane locks were conditionally released at 16:45:08–16:45:18 UTC. The direct authenticated SSM evidence tunnel and loopback listener are closed; archive size/SHA verification passed. No screenshots were staged to an external bucket and no profiles or credential fixtures were transferred.

Exact filenames, hashes, per-image review provenance and preserved diagnostic classifications are in `independent-visual-review.json`; cleanup receipts are in `cleanup-state.json` and `cleanup-result.txt`.
