# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Telemetry-expansion tests: draft abandonment, session start, workspace
switching, the rejection window, native import shims and the onboarding
funnel. Plain test functions only (no pytest fixtures) — this file also runs
under the fixture-free in-Blender runner. Split out of
``test_usage_analytics.py`` to respect the repo's 500-line file budget."""

from types import SimpleNamespace, ModuleType
from unittest.mock import patch
import sys


# Queue imports reach the auth module; the standalone stubbed-bpy environment
# intentionally does not install the platform keyring dependency.
if "keyring" not in sys.modules:
    sys.modules["keyring"] = ModuleType("keyring")


def _analytics_module():
    handlers = ModuleType("bpy.app.handlers")
    handlers.persistent = lambda fn: fn
    with patch.dict(sys.modules, {"bpy.app.handlers": handlers}):
        sys.modules.pop("mixar.bootstrap.analytics_module", None)
        from mixar.bootstrap import analytics_module
    return analytics_module


# ---------------------------------------------------------------------------
# Draft abandonment (structure-only snapshots)
# ---------------------------------------------------------------------------

def _draft_events():
    from mixar.modules.common.analytics import draft_events
    draft_events.reset_draft_state()
    return draft_events


def _imagegen_context(prompt="", reference_count=0):
    tab = SimpleNamespace(
        prompt=prompt, mode="image_gen", model="model-slug", style="realistic",
        aspect_ratio="1:1", resolution="1024", use_reference_images=True,
        reference_images=[SimpleNamespace()] * reference_count)
    sidebar = SimpleNamespace(tab_imagegen=tab)
    return SimpleNamespace(scene=SimpleNamespace(mixie_moodboard_sidebar=sidebar))


def test_draft_snapshot_never_contains_prompt_text_and_has_exact_keys() -> None:
    draft_events = _draft_events()
    sentinel = "TOPSECRET-SENTINEL a dragon guarding my private castle"
    snapshot = draft_events.snapshot_draft(_imagegen_context(sentinel), "image_gen")
    assert snapshot is not None
    assert "TOPSECRET" not in repr(snapshot)
    assert set(snapshot) == {
        "capability", "has_prompt", "prompt_length_bucket", "mode", "model",
        "style", "aspect_ratio", "resolution", "use_reference_images",
        "reference_image_count",
    }
    assert snapshot["has_prompt"] is True
    assert snapshot["prompt_length_bucket"] == "21-100"


def test_default_draft_snapshots_to_none() -> None:
    draft_events = _draft_events()
    assert draft_events.snapshot_draft(_imagegen_context(), "image_gen") is None


def test_video_gen_snapshot_is_mode_model_and_bucket_only() -> None:
    draft_events = _draft_events()
    tab = SimpleNamespace(prompt="SECRET-CLIP a slow pan over the castle",
                          mode="video_gen", model="seedance-2.0")
    context = SimpleNamespace(scene=SimpleNamespace(
        mixie_moodboard_sidebar=SimpleNamespace(tab_video_gen=tab)))
    snapshot = draft_events.snapshot_draft(context, "video_gen")
    assert snapshot is not None
    assert "SECRET-CLIP" not in repr(snapshot)
    assert set(snapshot) == {
        "capability", "has_prompt", "prompt_length_bucket", "mode", "model"}
    tab.prompt = ""
    assert draft_events.snapshot_draft(context, "video_gen") is None


def test_submitted_marker_suppresses_abandonment_until_reentry() -> None:
    draft_events = _draft_events()
    context = _imagegen_context("a dragon")
    draft_events.note_panel_entered("image_gen")
    # Feature-key spelling must normalize onto the capability.
    draft_events.note_generation_submitted("imagegen")
    with patch.object(draft_events, "capture") as emit:
        draft_events.capture_draft_abandoned(context, "image_gen", 5.0)
        emit.assert_not_called()
        # Re-entering the panel resets the baseline; the draft is live again.
        draft_events.note_panel_entered("image_gen")
        draft_events.capture_draft_abandoned(context, "image_gen", 5.0)
    emit.assert_called_once()
    assert emit.call_args.args[1]["dwell_seconds"] == 5


def test_abandonment_dedupes_identical_consecutive_snapshots() -> None:
    draft_events = _draft_events()
    context = _imagegen_context("a dragon")
    draft_events.note_panel_entered("image_gen")
    with patch.object(draft_events, "capture") as emit:
        draft_events.capture_draft_abandoned(context, "image_gen", 3.0)
        draft_events.capture_draft_abandoned(context, "image_gen", 9.0)
        # A different prompt in the same length bucket is the SAME structure
        # — still deduplicated (snapshots never contain the text itself).
        draft_events.capture_draft_abandoned(
            _imagegen_context("a bigger dragon"), "image_gen", 9.0)
        assert emit.call_count == 1
        draft_events.capture_draft_abandoned(
            _imagegen_context("a dragon", reference_count=2), "image_gen", 4.0)
    assert emit.call_count == 2


def _pbr_generation_context(prompt="", reference=None, view_count=0):
    views = [SimpleNamespace()] * view_count + [None] * (4 - view_count)
    tab = SimpleNamespace(
        prompt=prompt, mode="tripo_texture", model="tripo-texture-v1",
        multi_view=view_count > 0, style_only=False, use_selected_image=True,
        reference_image=reference,
        front_image=views[0], left_image=views[1],
        back_image=views[2], right_image=views[3])
    sidebar = SimpleNamespace(tab_pbr_gen=tab)
    return SimpleNamespace(scene=SimpleNamespace(mixie_moodboard_sidebar=sidebar))


def test_pbr_generation_snapshot_has_exact_keys_and_no_prompt_text() -> None:
    draft_events = _draft_events()
    sentinel = "PBR-SECRET weathered bronze with verdigris streaks"
    snapshot = draft_events.snapshot_draft(
        _pbr_generation_context(sentinel, view_count=3), "pbr_generation")
    assert snapshot is not None
    assert "PBR-SECRET" not in repr(snapshot)
    assert set(snapshot) == {
        "capability", "has_prompt", "prompt_length_bucket", "mode", "model",
        "multi_view", "style_only", "use_selected_image",
        "reference_image_attached", "view_image_count",
    }
    assert snapshot["view_image_count"] == 3
    # No prompt, no reference, no views = default draft, never emitted.
    assert draft_events.snapshot_draft(
        _pbr_generation_context(), "pbr_generation") is None
    # A reference image alone is a non-default draft.
    assert draft_events.snapshot_draft(
        _pbr_generation_context(reference=SimpleNamespace()),
        "pbr_generation") is not None


def test_new_moodboard_panels_map_to_capabilities() -> None:
    draft_events = _draft_events()
    assert draft_events.capability_for_panel("Character Parts") == "character_parts"
    assert draft_events.capability_for_panel("PBR Generation") == "pbr_generation"
    # Character Parts is operator/list-driven — mapped for panel/dwell
    # tracking, but it deliberately never produces a draft snapshot.
    context = SimpleNamespace(scene=SimpleNamespace(
        mixie_moodboard_sidebar=SimpleNamespace()))
    assert draft_events.snapshot_draft(context, "character_parts") is None


# ---------------------------------------------------------------------------
# Session start
# ---------------------------------------------------------------------------

def test_session_started_once_guard_and_property_shapes() -> None:
    from mixar.modules.common.analytics import session_events

    session_events.reset_session_started()
    with (patch.object(session_events, "capture") as emit,
          patch.object(session_events, "_seconds_to_ready", return_value=12)):
        session_events.capture_session_started("startup_token", refreshed=True)
        session_events.capture_session_started("sso_relogin")
    emit.assert_called_once()
    assert emit.call_args.args[0] == "app.session_started"
    assert emit.call_args.args[1] == {
        "method": "startup_token", "refreshed": True, "seconds_to_ready": 12}

    session_events.reset_session_started()
    with (patch.object(session_events, "capture") as emit,
          patch.object(session_events, "_seconds_to_ready", return_value=None)):
        session_events.capture_session_started("interactive_login")
    # No refreshed key outside the startup path; no seconds when unknown.
    assert emit.call_args.args[1] == {"method": "interactive_login"}


# ---------------------------------------------------------------------------
# Workspace switching
# ---------------------------------------------------------------------------

def test_workspace_names_outside_allowlist_report_as_custom() -> None:
    analytics_module = _analytics_module()
    assert analytics_module._safe_workspace_name("Layout") == "Layout"
    assert analytics_module._safe_workspace_name("Zen Mode") == "Zen Mode"
    assert analytics_module._safe_workspace_name("Raj Secret Client") == "custom"


def test_workspace_scan_seeds_then_reports_switch() -> None:
    analytics_module = _analytics_module()
    analytics_module._last_workspaces.clear()
    window = SimpleNamespace(
        workspace=SimpleNamespace(name="Layout"), as_pointer=lambda: 3)
    wm = SimpleNamespace(windows=[window])
    with patch.object(analytics_module, "capture") as emit:
        analytics_module._scan_workspaces(10.0, wm)
        emit.assert_not_called()  # first observation seeds
        window.workspace = SimpleNamespace(name="My Own Space")
        analytics_module._scan_workspaces(15.5, wm)
    assert emit.call_args.args[1] == {
        "workspace": "custom", "previous_workspace": "Layout",
        "previous_duration_seconds": 5.5}


# ---------------------------------------------------------------------------
# Rejection window
# ---------------------------------------------------------------------------

def _rejection_events():
    from mixar.modules.common.analytics import rejection_events
    rejection_events.reset_rejection_state()
    return rejection_events


def test_undo_within_window_rejects_and_clears() -> None:
    rejection_events = _rejection_events()
    with (patch.object(rejection_events, "capture") as emit,
          patch.object(rejection_events.time, "monotonic",
                       side_effect=[100.0, 130.0])):
        rejection_events.note_output_landed("generation", {11, 22})
        rejection_events.on_undo()
    emit.assert_called_once()
    assert emit.call_args.args[1] == {
        "trigger": "undo", "source": "generation", "seconds_since_output": 30}
    with (patch.object(rejection_events, "capture") as emit,
          patch.object(rejection_events.time, "monotonic", return_value=131.0)):
        rejection_events.on_undo()  # one rejection per landing
    emit.assert_not_called()


def test_undo_after_window_emits_nothing() -> None:
    rejection_events = _rejection_events()
    with (patch.object(rejection_events, "capture") as emit,
          patch.object(rejection_events.time, "monotonic",
                       side_effect=[100.0, 170.0])):
        rejection_events.note_output_landed("generation", {11})
        rejection_events.on_undo()
    emit.assert_not_called()


def test_deleted_tracked_object_rejects_with_delete_trigger() -> None:
    rejection_events = _rejection_events()
    fake_bpy = SimpleNamespace(data=SimpleNamespace(
        objects=[SimpleNamespace(session_uid=22)]))  # uid 11 vanished
    with (patch.object(rejection_events, "capture") as emit,
          patch.object(rejection_events.time, "monotonic",
                       side_effect=[100.0, 110.0]),
          patch.dict(sys.modules, {"bpy": fake_bpy})):
        rejection_events.note_output_landed("generation", {11, 22})
        rejection_events.check_deleted_objects()
    emit.assert_called_once()
    assert emit.call_args.args[1] == {
        "trigger": "delete", "source": "generation", "seconds_since_output": 10}
    assert not rejection_events.has_tracked_uids()  # landing cleared


def test_agent_landing_undo_reports_agent_source() -> None:
    rejection_events = _rejection_events()
    with (patch.object(rejection_events, "capture") as emit,
          patch.object(rejection_events.time, "monotonic",
                       side_effect=[100.0, 120.0])):
        rejection_events.note_output_landed("agent", None)
        rejection_events.on_undo()
    assert emit.call_args.args[1] == {
        "trigger": "undo", "source": "agent", "seconds_since_output": 20}


# ---------------------------------------------------------------------------
# Native import shims
# ---------------------------------------------------------------------------

def test_native_import_wrapper_captures_initiated_without_filepath() -> None:
    from mixar.modules.common.ui.operators import native_import_ops
    from mixar.modules.common.analytics import import_events

    delegated = {"RUNNING_MODAL"}
    invoked = []

    def _fake_importer(*args, **kwargs):
        invoked.append(args)
        return delegated

    # Patch the resolver, not bpy.ops (dynamic submodules ignore patching).
    with (
        patch.object(import_events, "capture") as emit,
        patch.object(native_import_ops, "_resolve_operator",
                     return_value=_fake_importer),
    ):
        result = native_import_ops._execute_import(SimpleNamespace(
            import_format="OBJ", operator_namespace="wm",
            operator_name="obj_import"), SimpleNamespace())

    assert result == delegated
    emit.assert_called_once()
    assert emit.call_args.args[:2] == (
        "import.initiated", {"format": "OBJ", "via": "file_menu"})
    assert "filepath" not in emit.call_args.args[1]
    assert invoked == [('INVOKE_DEFAULT',)]


# ---------------------------------------------------------------------------
# Onboarding funnel
# ---------------------------------------------------------------------------

def _onboarding_transition(previous_step, to_step, opted_out):
    # The onboarding core package pulls in GPU-drawing modules at import
    # time; stub them like conftest stubs bpy (MagicMock so attribute
    # imports such as batch_for_shader resolve).
    from unittest.mock import MagicMock
    for name in ("gpu", "gpu.state", "gpu.shader", "gpu.types", "gpu.matrix",
                 "gpu_extras", "gpu_extras.batch", "blf"):
        if name not in sys.modules:
            sys.modules[name] = MagicMock(name=name)
    from mixar.modules.onboarding.core import state
    from mixar.modules.onboarding import constants as ob_constants

    tour_driver = ModuleType("tour_driver")
    tour_driver.apply_step = lambda *args, **kwargs: None
    wm = SimpleNamespace()
    setattr(wm, ob_constants.WM_PROP_STEP, previous_step)
    setattr(wm, ob_constants.WM_PROP_OPTED_OUT, opted_out)
    context = SimpleNamespace(
        window_manager=wm, scene=SimpleNamespace(mixie_chat_user_id=""))
    with (
        patch.dict(sys.modules,
                   {"mixar.modules.onboarding.core.tour_driver": tour_driver}),
        patch("mixar.modules.common.analytics.capture.capture") as emit,
    ):
        state.transition_to(to_step, context)
    return [(call.args[0], call.args[1]) for call in emit.call_args_list]


def test_onboarding_transition_emits_step_changed() -> None:
    events = _onboarding_transition("WELCOME", "INFO_MOODBOARD", False)
    assert ("onboarding.step_changed",
            {"from_step": "WELCOME", "to_step": "INFO_MOODBOARD"}) in events
    assert all(name != "onboarding.finished" for name, _ in events)


def test_onboarding_finish_distinguishes_completed_from_skipped() -> None:
    completed = _onboarding_transition("COMPLETION", "DONE", False)
    assert ("onboarding.finished",
            {"outcome": "completed", "last_step": "COMPLETION"}) in completed

    skipped = _onboarding_transition("WELCOME", "DONE", True)
    assert ("onboarding.finished",
            {"outcome": "skipped", "last_step": "WELCOME"}) in skipped


# ---------------------------------------------------------------------------
# Startup-noise fixes (first live export findings)
# ---------------------------------------------------------------------------

def test_session_started_attaches_a_context_when_none_given() -> None:
    """Without a context the event misses instance_id and cannot be joined
    to its session_ended."""
    from mixar.modules.common.analytics import session_events

    session_events.reset_session_started()
    with (patch.object(session_events, "capture") as emit,
          patch.object(session_events, "_seconds_to_ready", return_value=None)):
        session_events.capture_session_started("interactive_login")
    assert emit.call_args.kwargs["context"] is not None


def _panel_scan_context(region):
    space = SimpleNamespace(mixie_mode="MOODBOARD", show_region_ui=True)
    area = SimpleNamespace(
        type="MIXIE", spaces=SimpleNamespace(active=space), regions=[region])
    window = SimpleNamespace(screen=SimpleNamespace(areas=[area]))
    return SimpleNamespace(window_manager=SimpleNamespace(windows=[window]))


def test_panel_settling_from_unsupported_is_a_seed_not_a_switch() -> None:
    """A region seeded pre-catalog reads UNSUPPORTED; it settling into its
    first real tab is initialization, not a user switch."""
    analytics_module = _analytics_module()
    region = SimpleNamespace(
        type="UI", active_panel_category="UNSUPPORTED", as_pointer=lambda: 11)
    context = _panel_scan_context(region)
    analytics_module._last_panels.clear()
    analytics_module._last_sidebars.clear()
    analytics_module._suppressed_panels.clear()
    with (patch.object(analytics_module.bpy, "context", context),
          patch.object(analytics_module.rejection_events, "check_deleted_objects",
                       lambda: None),
          patch.object(analytics_module, "capture") as emit):
        analytics_module._scan_panels()          # seeds UNSUPPORTED
        region.active_panel_category = "Image Gen"
        analytics_module._scan_panels()          # settles: must stay silent
        emit.assert_not_called()
        region.active_panel_category = "Model Gen"
        analytics_module._scan_panels()          # a real switch still reports
    emit.assert_called_once()
    assert emit.call_args.args[1]["previous_panel"] == "Image Gen"


def test_load_post_reseeds_the_chat_mode_watcher() -> None:
    """A mode carried over from the pre-load scene must not read as a switch
    (the startup-file load emitted a phantom agent.mode_changed)."""
    analytics_module = _analytics_module()
    analytics_module._last_chat_mode = "GENERATE"
    analytics_module._last_history = True
    analytics_module._on_load(None)
    assert analytics_module._last_chat_mode is None
    assert analytics_module._last_history is None

    scene = SimpleNamespace(mixie_chat_mode="AGENT")
    wm = SimpleNamespace(mixie_chat_history_visible=False)
    context = SimpleNamespace(scene=scene, window_manager=wm)
    with (patch.object(analytics_module.bpy, "context", context),
          patch.object(analytics_module, "session_started_emitted", return_value=True),
          patch.object(analytics_module, "capture") as emit):
        analytics_module._scan_chat_state()      # first observation: seed only
        emit.assert_not_called()
        scene.mixie_chat_mode = "GENERATE"
        analytics_module._scan_chat_state()      # a real switch still reports
    assert emit.call_args.args[1] == {"mode": "GENERATE"}


def test_chat_state_changes_before_session_start_never_report() -> None:
    """The startup load_post predates the analytics handler, so pre-auth
    mode flips (file load + legacy sanitizing) must read as seeding."""
    analytics_module = _analytics_module()
    analytics_module._last_chat_mode = None
    analytics_module._last_history = None
    scene = SimpleNamespace(mixie_chat_mode="GENERATE")
    wm = SimpleNamespace(mixie_chat_history_visible=False)
    context = SimpleNamespace(scene=scene, window_manager=wm)
    with (patch.object(analytics_module.bpy, "context", context),
          patch.object(analytics_module, "session_started_emitted", return_value=False),
          patch.object(analytics_module, "capture") as emit):
        analytics_module._scan_chat_state()
        scene.mixie_chat_mode = "AGENT"          # sanitizer flips it pre-auth
        analytics_module._scan_chat_state()
        emit.assert_not_called()
    # The last pre-auth value is the seed the post-auth watcher starts from.
    assert analytics_module._last_chat_mode == "AGENT"


def test_session_started_mints_the_instance_id_when_unset() -> None:
    """wm.mixie_instance_id is normally minted lazily long after login;
    session_started must not miss the join key its session_ended carries."""
    from mixar.modules.common.analytics import session_events

    session_events.reset_session_started()
    wm = SimpleNamespace(mixie_instance_id="")
    context = SimpleNamespace(window_manager=wm)
    with (patch.object(session_events, "capture"),
          patch.object(session_events, "_seconds_to_ready", return_value=None)):
        session_events.capture_session_started("startup_token", context=context)
    assert wm.mixie_instance_id

    session_events.reset_session_started()
    wm = SimpleNamespace(mixie_instance_id="existing-id")
    with (patch.object(session_events, "capture"),
          patch.object(session_events, "_seconds_to_ready", return_value=None)):
        session_events.capture_session_started(
            "startup_token", context=SimpleNamespace(window_manager=wm))
    assert wm.mixie_instance_id == "existing-id"


def test_toast_click_is_denylisted_operator_chrome() -> None:
    from mixar.modules.common.analytics.constants import IGNORED_OPERATORS

    assert "notification.toast_click" in IGNORED_OPERATORS
    assert "notification.toast_hover" in IGNORED_OPERATORS
