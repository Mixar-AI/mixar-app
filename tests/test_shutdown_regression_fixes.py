# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "scripts" / "mixar"


def read_src(relative_path: str) -> str:
    return (SRC / relative_path).read_text(encoding="utf-8")


def test_lookdev360_unregister_skips_unregistered_classes():
    source = read_src("modules/moodboard/ui/operators/lookdev360_ops.py")
    tree = ast.parse(source)
    unregister = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "unregister"
    )

    assert "is_registered" in ast.unparse(unregister)
    assert "unregister_class(cls)" in ast.unparse(unregister)


def test_agent_shutdown_disconnect_skips_scene_state_updates():
    bootstrap_source = read_src("bootstrap/agent_connection.py")
    manager_source = read_src("modules/space_mixie_chat/core/connection_manager.py")

    assert "manager.disconnect(update_session_state=False)" in bootstrap_source
    assert "def disconnect(self, update_session_state: bool = True)" in manager_source
    assert "if update_session_state:" in manager_source


def test_agent_shutdown_suppresses_disconnect_callback_scene_writes():
    manager_source = read_src("modules/space_mixie_chat/core/connection_manager.py")

    assert "self._is_shutting_down" in manager_source
    assert "if self._is_shutting_down:" in manager_source


def test_agent_bubble_pill_regions_exit_before_free():
    source = (
        ROOT / "src" / "source" / "blender" / "editors"
        / "space_agent_bubble" / "space_agent_bubble.cc"
    ).read_text(encoding="utf-8")
    remove_block_start = source.index("DELETE (don't just hide) the WINDOW + TOOLS")
    remove_block = source[
        remove_block_start:source.index("ED_area_init(C, pill_win, pill_area);")
    ]

    assert "ED_region_exit(C, region)" in remove_block
    assert (
        remove_block.index("ED_region_exit(C, region)")
        < remove_block.index("BKE_area_region_free(st, region)")
    )


def test_startup_cache_fetches_do_not_schedule_redraw_after_shutdown():
    for relative_path, scheduler_name, scheduled_callback in (
        (
            "bootstrap/generation_catalog_cache.py",
            "_schedule_catalog_swapped",
            "_on_catalog_swapped",
        ),
        (
            "bootstrap/chat_generate_options_cache.py",
            "_schedule_redraw",
            "trigger_ui_redraw",
        ),
    ):
        source = read_src(relative_path)
        functions = {
            node.name: node
            for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef)
        }
        scheduler = functions[scheduler_name]
        unregister = functions["unregister"]

        lifecycle_block = next(
            nested
            for statement in scheduler.body
            if isinstance(statement, ast.Try)
            for nested in statement.body
            if isinstance(nested, ast.With)
            and any(ast.unparse(item.context_expr) == "_lock" for item in nested.items)
        )
        lifecycle_source = ast.unparse(lifecycle_block)
        register_call = f"bpy.app.timers.register({scheduled_callback}"

        assert "if _shutdown_requested:" in lifecycle_source
        assert register_call in lifecycle_source
        assert lifecycle_source.index("if _shutdown_requested:") < lifecycle_source.index(
            register_call
        )

        unregister_source = ast.unparse(unregister)
        assert "_shutdown_requested = True" in unregister_source
        assert scheduled_callback in unregister_source
        assert "bpy.app.timers.unregister" in unregister_source


def test_agent_connection_callbacks_skip_main_thread_timers_during_shutdown():
    manager_source = read_src("modules/space_mixie_chat/core/connection_manager.py")
    on_connected_start = manager_source.index("        def on_connected():")
    on_connected_block = manager_source[
        on_connected_start:manager_source.index("        def on_disconnected", on_connected_start)
    ]

    assert "if self._is_shutting_down:" in on_connected_block
    assert (
        on_connected_block.index("if self._is_shutting_down:")
        < on_connected_block.index("run_on_main_thread")
    )


def test_main_thread_executor_rejects_late_timers_after_cleanup():
    executor_source = read_src("modules/space_mixie_chat/core/main_thread_executor.py")
    run_on_main_thread = executor_source[
        executor_source.index("def run_on_main_thread")
        :executor_source.index("def cleanup")
    ]
    cleanup = executor_source[executor_source.index("def cleanup"):]

    assert "_shutdown_requested" in executor_source
    assert "if _shutdown_requested:" in run_on_main_thread
    assert "_shutdown_requested = True" in cleanup


def test_headless_sandbox_uses_windows_parent_liveness_probe():
    source = read_src("headless/headless_main.py")

    assert "def _pid_alive_windows" in source
    assert 'ctypes.WinDLL("kernel32", use_last_error=True)' in source
    assert "ctypes.get_last_error() == 5" in source
    assert "OpenProcess" in source
    assert "GetExitCodeProcess" in source
    assert 'os.name == "nt"' in source
    assert "os.kill(pid, 0)" in source


def test_sandbox_supervisor_uses_windows_popen_flags():
    source = read_src("bootstrap/sandbox_supervisor.py")

    assert "def _sandbox_popen_kwargs" in source
    assert "CREATE_NEW_PROCESS_GROUP" in source
    assert "creationflags" in source
    assert "start_new_session" in source
    assert 'os.name == "nt"' in source
    assert "re.sub" in source
