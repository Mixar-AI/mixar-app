// SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
// SPDX-License-Identifier: GPL-3.0-or-later

// Derive MCP tool annotations from a tool name so every tool (including the
// ~230 vendored Blender tools) gets safety hints — readOnlyHint /
// destructiveHint / idempotentHint / openWorldHint — without hand-tagging each
// one or editing vendored files. Heuristic but conservative: read-only is
// asserted only for clear queries; deletes are destructive; dynamic-dispatch
// and external-world tools are open-world.

const READ =
  /(_info$|_info_|_list$|_get$|_get_|_data$|_summary|_describe|_analyze|analyze_|_validate|validate_|_screenshot|_capture|_status$|_catalog$|_models$|_health$|_graph$|_history$|_roots$|_children$|_descendants$|_ancestors$|scene_info|object_info|scene_graph|operation_history|list_advanced_tools)/;
const DESTRUCTIVE = /(_delete$|_delete_|_remove$|_remove_|_clear$)/;
const SETLIKE = /(_set_|_set$|_assign$|_transform$|_apply$|_apply_|_reorder$)/;
const OPENWORLD =
  /(execute_script|advanced_tool|_generate$|_generate_|generation_|provider_keys|python_exec|import_file|_import$)/;

/**
 * @param {string} name  tool name (e.g. "blender_object_delete")
 * @returns {object | undefined}  MCP annotations, or undefined if none apply
 */
export function deriveAnnotations(name) {
  const n = (name || "").toLowerCase();
  const destructive = DESTRUCTIVE.test(n);
  const readOnly = READ.test(n) && !destructive && !SETLIKE.test(n);

  const a = {};
  if (readOnly) {
    a.readOnlyHint = true;
    a.idempotentHint = true;
  }
  if (destructive) a.destructiveHint = true;
  if (!readOnly && !destructive && SETLIKE.test(n)) a.idempotentHint = true;
  if (OPENWORLD.test(n)) a.openWorldHint = true;
  return Object.keys(a).length ? a : undefined;
}
