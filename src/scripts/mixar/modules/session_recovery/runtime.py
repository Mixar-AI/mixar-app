# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Crash-safe sessions inside the running app (the bpy half).

- Save points: ``request_save_point`` from the agent executor, the turn end
  and the generation import; a 1 s timer asks the scheduler and writes with
  the native ``wm.save_auto_save`` (full document, recovery header, dirty
  images packed, no save handlers), then files it in the journal.
- Startup: before this launch's own journal exists, the journals of earlier
  launches are read and ``decision.find_offer`` picks what to offer. The
  splash heads with it; with no splash a dialog asks. Restore is the default.
- Restore: read the save point, give the document its path back in memory
  (nothing is written to the project), adopt the generations that were
  running, and put a Continue notice in every tab whose agent was working.

The rules live in ``journal`` (files, liveness), ``decision`` (what to
offer, the crash-loop guard) and ``scheduler`` (when to save).
"""

from __future__ import annotations

import atexit
import os
import time
import uuid

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import iface_, rpt_

from . import decision, jobs, journal, liveness
from .scheduler import SavePointScheduler

logger = get_logger(__name__)

TICK_S = 1.0
CONFIRM_AFTER_S = 20.0
# Modal operators that run for a whole agent turn (or a background job) and
# hold no half-applied edit; any other modal (a drag, a knife cut) defers the
# save. Same list as the native autosave (wm_files.cc).
PASSIVE_MODALS = frozenset({
    "MIXAR_OT_agent_viewport_block",
    "MIXIE_CHAT_OT_undo_shield",
    "MIXIE_OT_train_asset_model",
})
_BUSY_JOBS = ("RENDER", "OBJECT_BAKE", "COMPOSITE")
_AGENT_WORKING = ("busy", "modifying", "awaiting_input")

CONTINUE_PREFIX = "crash_continue:"
DISMISS_ACTION = "crash_dismiss"
BUBBLE_PREFIX = "crash-resume-"
CONTINUE_TEXT = (
    "Mixar closed unexpectedly while you were working, and my scene was restored "
    "from the last save point. Continue the interrupted task. Check the scene first: "
    "your last steps before the crash may be missing."
)

_state = {
    "journal": None,
    "scheduler": None,
    "offer": None,
    "decided": False,
    "prompted": False,
    "restoring": False,
    "restore_target": None,
}


# =============================================================================
# Small helpers
# =============================================================================

def enabled() -> bool:
    """Off in background runs and in the agent's sandbox child process."""
    if bpy.app.background:
        return False
    return not os.environ.get("MIXAR_SANDBOX_PARENT_PID")


def _now() -> float:
    return time.time()


def _mono() -> float:
    return time.monotonic()


def _main_window():
    try:
        from mixar.modules.space_mixie_chat.core.checkpoint_timeline import _main_window as main
        return main()
    except Exception:  # noqa: BLE001
        return getattr(bpy.context, "window", None)


def tempdir_base() -> str:
    session = bpy.app.tempdir
    if session:
        return os.path.dirname(os.path.normpath(session))
    import tempfile
    return tempfile.gettempdir()


def native_autosave_path() -> str:
    """Where ``WM_autosave_write`` puts this process's file (wm_files.cc)."""
    pid = abs(os.getpid())
    path = bpy.data.filepath or ""
    if path:
        base = os.path.basename(path)
        filename = f"{base[:len(base) - 6]}_{pid}_autosave.mixar"
    else:
        filename = f"{pid}_autosave.mixar"
    return os.path.join(tempdir_base(), filename)


def _op_idname(op) -> str:
    idname = getattr(op, "bl_idname", "") or ""
    if "." in idname:
        prefix, name = idname.split(".", 1)
        return f"{prefix.upper()}_OT_{name}"
    return idname


def _busy() -> bool:
    """True while a save would land in the middle of something."""
    if _state["restoring"]:
        return True
    try:
        from mixar.modules.space_mixie_chat.core import turn_checkpoints
        if turn_checkpoints.is_restoring():
            return True
    except Exception:  # noqa: BLE001
        pass
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return True
    for window in wm.windows:
        for op in getattr(window, "modal_operators", ()):
            if _op_idname(op) not in PASSIVE_MODALS:
                return True
    for kind in _BUSY_JOBS:
        try:
            if bpy.app.is_job_running(kind):
                return True
        except (TypeError, ValueError):
            pass
    try:
        from mixar.modules.space_mixie_chat.core import main_thread_executor as mte
        if mte.has_pending_requests() or mte.get_inflight_script():
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _session_manager():
    from mixar.modules.space_mixie_chat.core.session import get_session_manager
    return get_session_manager()


def _tab_scenes() -> list:
    try:
        from mixar.modules.space_mixie_chat.ui.operators.scene_tab_ops import real_scenes
        return list(real_scenes())
    except Exception:  # noqa: BLE001
        return list(bpy.data.scenes)


def agent_scenes() -> list:
    """Tabs whose agent is working right now (a live turn or an open run)."""
    found = []
    try:
        session = _session_manager()
    except Exception:  # noqa: BLE001
        return found
    for scene in _tab_scenes():
        try:
            sid = session.get_session_id(scene)
            state = str(getattr(session.get_state(scene), "value", "") or "").lower()
            if sid and (state in _AGENT_WORKING or session.run_open(scene)):
                found.append({"scene": scene.name, "session_id": sid})
        except Exception:  # noqa: BLE001
            continue
    return found


def _job_records() -> list:
    try:
        from mixar.modules.common.job_queue.core.queue_manager import all_queues
        return jobs.describe(j for q in all_queues() for j in q.snapshot())
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[RECOVERY] job snapshot skipped: {e}")
        return []


# =============================================================================
# Save points
# =============================================================================

def request_save_point(reason: str) -> None:
    """Ask for a save point soon (coalesced, never blocks). Never raises."""
    scheduler = _state["scheduler"]
    if scheduler is None:
        return
    try:
        scheduler.request(reason, _mono())
    except Exception:  # noqa: BLE001
        pass


def note_snapshot(path: str, original_path: str = "") -> None:
    """A turn checkpoint was written: an older candidate at no extra cost."""
    jr = _state["journal"]
    if jr is None or not path:
        return
    try:
        jr.add_snapshot(path, now=_now(), original_path=original_path)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[RECOVERY] snapshot note skipped: {e}")


def write_save_point(reasons) -> dict | None:
    """Write one save point now. Returns its record, or None."""
    jr, scheduler = _state["journal"], _state["scheduler"]
    if jr is None:
        return None
    reason = ",".join(reasons) or "manual"
    path = native_autosave_path()
    started = time.perf_counter()
    ok = False
    try:
        window = _main_window()
        if window is not None:
            with bpy.context.temp_override(window=window):
                result = bpy.ops.wm.save_auto_save()
        else:
            result = bpy.ops.wm.save_auto_save()
        ok = 'FINISHED' in result and os.path.isfile(path)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[RECOVERY] save point failed: {e}")
    cost = time.perf_counter() - started
    if not ok:
        if scheduler is not None:
            scheduler.record_save(_mono(), cost, False)
        return None
    try:
        record = jr.add_save_point(
            path, now=_now(), reason=reason, cost_s=cost,
            original_path=bpy.data.filepath or "",
            scenes=[s.name for s in _tab_scenes()],
            agent_scenes=agent_scenes(), jobs=_job_records(),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[RECOVERY] save point not filed: {e}")
        if scheduler is not None:
            scheduler.record_save(_mono(), cost, False)
        return None
    if scheduler is not None:
        scheduler.record_save(_mono(), cost, True)
    logger.info(f"[RECOVERY] save point {record['seq']} ({reason}) "
                f"{record['bytes'] / 1e6:.1f} MB in {cost * 1000:.0f} ms")
    return record


def _tick():
    try:
        scheduler = _state["scheduler"]
        if scheduler is None:
            return None
        busy = _busy()
        due, reasons = scheduler.due(_mono(), busy=busy, dirty=bool(bpy.data.is_dirty))
        if due:
            write_save_point(reasons)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[RECOVERY] tick skipped: {e}")
    return TICK_S


# =============================================================================
# Handlers
# =============================================================================

@bpy.app.handlers.persistent
def _on_depsgraph_update(*_args):
    scheduler = _state["scheduler"]
    if scheduler is not None:
        scheduler.changes += 1


@bpy.app.handlers.persistent
def _on_save_post(filepath, *_args):
    """A real save of the document (a copy keeps its own path) is recorded,
    and the save points older than it are dropped."""
    jr = _state["journal"]
    if jr is None:
        return
    try:
        path = filepath if isinstance(filepath, str) else ""
        # A copy (turn checkpoint, export) keeps the document's own path.
        if path and bpy.data.filepath and os.path.normpath(path) == os.path.normpath(bpy.data.filepath):
            jr.note_user_save(path, now=_now())
            if _state["scheduler"] is not None:
                _state["scheduler"].reset(_mono())
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[RECOVERY] save_post skipped: {e}")


@bpy.app.handlers.persistent
def _on_load_post(*_args):
    """Another document was opened: what the journal held was the old one's.
    A crash restore and a turn-checkpoint jump keep it."""
    jr = _state["journal"]
    if jr is None or _state["restoring"]:
        return
    try:
        from mixar.modules.space_mixie_chat.core import turn_checkpoints
        if turn_checkpoints.is_restoring():
            return
    except Exception:  # noqa: BLE001
        pass
    try:
        jr.reset_document(bpy.data.filepath or "")
        if _state["scheduler"] is not None:
            _state["scheduler"].reset(_mono())
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[RECOVERY] load_post skipped: {e}")


def _on_exit():
    """Clean quit (atexit never runs after a crash): nothing to recover.
    bpy is already freed here; only files are touched."""
    jr = _state["journal"]
    if jr is None:
        return
    try:
        attempt = jr.data.get("restore_attempt") or {}
        if attempt and not attempt.get("confirmed"):
            # The restored document ran until a clean quit: the restore worked.
            _confirm_restore_files()
        jr.close_clean()
    except Exception:  # noqa: BLE001
        pass
    _state["journal"] = None


# =============================================================================
# Startup: what to offer
# =============================================================================

def _quit_mtime(base: str) -> float:
    path = os.path.join(base, decision.QUIT_FILE)
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _pid_alive(pid) -> bool:
    try:
        return liveness.pid_alive(int(pid))
    except Exception:  # noqa: BLE001
        return True


def _find_offer(root: str) -> dict | None:
    base = tempdir_base()
    sessions = journal.list_sessions(root)
    return decision.find_offer(
        sessions, autosaves=decision.native_autosaves(base), quit_mtime=_quit_mtime(base),
        now=_now(), pid_alive=_pid_alive,
    )


def current_offer() -> dict | None:
    offer = _state["offer"]
    if not offer or _state["decided"] or not offer.get("target"):
        return None
    return offer


def _resolve_dirs(dirs, how: str) -> None:
    now = _now()
    for directory in dirs:
        if directory:
            try:
                journal.update_manifest(directory, resolved=how, resolved_at=now)
            except Exception:  # noqa: BLE001
                pass


def _retire_legacy(paths) -> None:
    """A native autosave with no journal cannot carry ``resolved``; it is
    renamed out of the autosave pattern instead (kept, never offered again)."""
    for path in paths:
        if path and os.path.isfile(path):
            try:
                os.replace(path, f"{path}.dismissed")
            except OSError:
                pass


def _resolve_others(offer: dict, how: str) -> None:
    older = offer.get("older", [])
    _resolve_dirs([o.get("dir", "") for o in older], how)
    _resolve_dirs(offer.get("debris", []), how)
    _retire_legacy([o["target"]["path"] for o in older if o.get("legacy")])


def describe(offer: dict) -> dict:
    """Text for the prompt."""
    target = offer["target"]
    name = offer.get("name") or iface_("Untitled")
    stamp = time.strftime("%H:%M", time.localtime(target["at"]))
    day = time.strftime("%b %d", time.localtime(target["at"]))
    if day != time.strftime("%b %d"):
        stamp = f"{day}, {stamp}"
    details = [f"{name} · {stamp}"]
    tabs = len(target.get("scenes") or [])
    if tabs > 1:
        details.append(iface_("{count} scene tabs").format(count=tabs))
    working = [a.get("scene", "") for a in target.get("agent_scenes") or []]
    if working:
        details.append(iface_("the agent was working in {tabs}").format(tabs=", ".join(working)))
    running = len(target.get("jobs") or [])
    if running:
        details.append(iface_("{count} generation(s) running").format(count=running))
    if offer.get("loop"):
        title = iface_("Mixar closed while restoring your work. Restore the previous save point?")
    else:
        title = iface_("Mixar closed unexpectedly. Restore your work?")
    return {"title": title, "detail": " · ".join(details)}


def draw_offer(layout, *, in_splash: bool) -> bool:
    """The restore block (splash head or dialog body). False when nothing
    is offered."""
    offer = current_offer()
    if offer is None:
        return False
    text = describe(offer)
    box = layout.box() if in_splash else layout
    if in_splash:
        box.emboss = 'NORMAL'
    col = box.column(align=False)
    col.label(text=text["title"], icon='RECOVER_LAST')
    col.label(text=text["detail"])
    if in_splash:
        row = col.row()
        row.scale_y = 1.4
        row.operator("mixar.restore_crashed_session", text=iface_("Restore"), icon='RECOVER_LAST')
        row.operator("mixar.discard_crashed_session", text=iface_("Start fresh"))
        layout.separator()
    else:
        col.operator("mixar.discard_crashed_session", text=iface_("Start fresh"), emboss=False)
    return True


def _prompt_tick():
    """Show the dialog once nothing else is on screen (the splash carries the
    same block while it is open)."""
    if current_offer() is None or _state["prompted"]:
        return None
    window = _main_window()
    if window is None:
        return 0.5
    try:
        from mixar.bootstrap import splash_menu
        if not splash_menu.onboarding_can_start():
            return 0.5
    except Exception:  # noqa: BLE001
        pass
    _state["prompted"] = True
    try:
        with bpy.context.temp_override(window=window):
            bpy.ops.mixar.crashed_session_prompt('INVOKE_DEFAULT')
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[RECOVERY] prompt failed: {e}")
    return None


# =============================================================================
# Restore
# =============================================================================

def discard_offer() -> None:
    """Start fresh: the crashed session is left alone (kept 7 days)."""
    offer = current_offer()
    _state["decided"] = True
    if offer is None:
        return
    if offer.get("dir"):
        _resolve_dirs([offer["dir"]], "dismissed")
    if offer.get("legacy"):
        _retire_legacy([offer["target"]["path"]])
    _resolve_others(offer, "dismissed")
    logger.info(f"[RECOVERY] user started fresh (crashed session {offer.get('session')})")


def restore_deferred() -> bool:
    """Restore on the next tick: the splash or dialog that asked is closed
    by the file read, so it must not run on their call stack."""
    if current_offer() is None:
        return False
    _state["decided"] = True
    bpy.app.timers.register(_restore_now, first_interval=0.05)
    return True


def _restore_now():
    offer = _state["offer"]
    if not offer or not offer.get("target"):
        return None
    target = offer["target"]
    jr = _state["journal"]
    # Crash-loop guard: record the attempt BEFORE the read. If the read (or
    # the next seconds) crashes, the next launch finds it unconfirmed.
    if jr is not None:
        jr.set_fields(restore_attempt={"point": target["path"], "from_session": offer.get("session"),
                                       "at": _now(), "confirmed": False})
    if offer.get("dir") and offer.get("failed_points"):
        try:
            journal.update_manifest(offer["dir"], failed_points=list(offer["failed_points"]))
        except Exception:  # noqa: BLE001
            pass
    try:
        from mixar.modules.space_mixie_chat.core.turn_checkpoints import _close_bubble_windows
        _close_bubble_windows()
    except Exception:  # noqa: BLE001
        pass
    _state["restoring"] = True
    ok = False
    try:
        window = _main_window()
        with bpy.context.temp_override(window=window):
            if target["kind"] == "project":
                result = bpy.ops.wm.open_mainfile(filepath=target["path"])
            else:
                result = bpy.ops.wm.recover_auto_save(filepath=target["path"])
        ok = 'FINISHED' in result
    except Exception as e:  # noqa: BLE001
        logger.error(f"[RECOVERY] restore read failed: {e}", exc_info=True)
    finally:
        _state["restoring"] = False
    if not ok:
        if jr is not None:
            jr.set_fields(restore_attempt=None)
        _report(rpt_("Mixar could not open the saved work. It is kept for the next launch."))
        _state["decided"] = False
        return None
    if target["kind"] != "project":
        try:
            from mixar.modules.space_mixie_chat.core.checkpoint_timeline import _keep_modified, _retitle
            original = target.get("original_path") or ""
            _retitle(original)
            bpy.app.timers.register(_keep_modified(original), first_interval=0.05)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[RECOVERY] retitle skipped: {e}")
    if offer.get("legacy") and jr is not None:
        # Take the loose autosave into this launch's journal so it is a
        # fallback here and never offered as a crashed session again.
        moved = os.path.join(jr.dir, "legacy-" + os.path.basename(target["path"]))
        try:
            journal.move_file(target["path"], moved)
            target = dict(target, path=moved)
            jr.set_fields(restore_attempt=dict(jr.data.get("restore_attempt") or {}, point=moved))
        except OSError:
            pass
    _state["restore_target"] = dict(target, source_dir=offer.get("dir", ""))
    if jr is not None:
        jr.set_fields(document_path=target.get("original_path") or "")
        jr.set_inherited([dict(target, source_dir=offer.get("dir", ""))])
    if _state["scheduler"] is not None:
        _state["scheduler"].reset(_mono())
    bpy.app.timers.register(_after_restore, first_interval=0.5)
    bpy.app.timers.register(_confirm_restore, first_interval=CONFIRM_AFTER_S)
    logger.info(f"[RECOVERY] restored {target['kind']} from {offer.get('session')} "
                f"(saved {time.strftime('%H:%M:%S', time.localtime(target['at']))})")
    return None


def _confirm_restore_files() -> None:
    offer = _state["offer"] or {}
    jr = _state["journal"]
    if jr is not None and jr.data.get("restore_attempt"):
        attempt = dict(jr.data["restore_attempt"], confirmed=True)
        jr.set_fields(restore_attempt=attempt)
    if offer.get("dir"):
        _resolve_dirs([offer["dir"]], "restored")
    _resolve_others(offer, "superseded")


def _confirm_restore():
    """The restored document has run for a while: the restore worked."""
    try:
        _confirm_restore_files()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[RECOVERY] confirm skipped: {e}")
    return None


def _after_restore():
    """After load_post handlers ran: generations, Continue notices, re-checks."""
    target = _state["restore_target"] or {}
    try:
        _adopt_jobs(target.get("jobs") or [])
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[RECOVERY] generation adoption skipped: {e}")
    for entry in target.get("agent_scenes") or []:
        scene = bpy.data.scenes.get(entry.get("scene", ""))
        if scene is not None:
            add_continue_notice(scene, entry.get("session_id", ""), target.get("at", 0.0))
    try:
        session = _session_manager()
        if any(session.is_connected(s) for s in bpy.data.scenes):
            from mixar.modules.space_mixie_chat.core.turn_resume import check_orphaned_turns
            check_orphaned_turns()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[RECOVERY] orphan check skipped: {e}")
    return None


def _adopt_jobs(records: list) -> None:
    adoptable, other = jobs.split(records)
    if not adoptable and not other:
        return
    from mixar.modules.common.job_queue.core import generic_jobs
    from mixar.modules.common.job_queue.core.queue_manager import get_queue
    classes = {name: getattr(generic_jobs, name) for name in jobs.GENERIC_CLASSES
               if hasattr(generic_jobs, name)}
    adopted = 0
    for record in adoptable:
        job = jobs.rebuild(record, classes)
        if job is not None and get_queue(record.get("feature_key") or "generation").adopt(job):
            adopted += 1
    if adopted:
        logger.info(f"[RECOVERY] re-attached {adopted} running generation(s)")
    if other:
        names = ", ".join(sorted({r.get("label") or r.get("cls", "") for r in other}))[:200]
        _report(rpt_("These generations were running when Mixar closed and could not be "
                     "re-attached: {names}").format(names=names))


def _report(text: str) -> None:
    logger.warning(f"[RECOVERY] {text}")
    try:
        from mixar.modules.common.notifications import get_notification_store
        get_notification_store().push("warning", rpt_("Restore"), body=text)
    except Exception:  # noqa: BLE001
        pass


# =============================================================================
# The Continue notice in the chat
# =============================================================================

def add_continue_notice(scene, session_id: str, saved_at: float) -> None:
    """A notice bubble: the agent was working, Continue or Start fresh."""
    if scene is None or not session_id or not hasattr(scene, "mixie_chat_messages"):
        return
    stamp = time.strftime("%H:%M", time.localtime(saved_at or _now()))
    title = rpt_("Mixar closed while the agent was working")
    body = rpt_("Your scene is back from the save point at {time}. Continue lets the agent "
                "check the scene and pick the task up from there.").format(time=stamp)
    content = f"**{title}**\n\n{body}"
    msg = scene.mixie_chat_messages.add()
    msg.bubble_id = f"{BUBBLE_PREFIX}{uuid.uuid4().hex[:8]}"
    msg.sender = "AGENT"
    msg.message_type = "AGENT"
    msg.content = content
    msg.text = content
    try:
        from mixar.modules.space_mixie_chat.core.markdown_parser import parse_markdown_to_segments
        from mixar.modules.space_mixie_chat.core.message_helpers import set_markdown_segments
        set_markdown_segments(msg, parse_markdown_to_segments(content, streaming=False))
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[RECOVERY] notice markdown skipped: {e}")
    msg.action_items.clear()
    go = msg.action_items.add()
    go.label = iface_("Continue")
    go.value = f"{CONTINUE_PREFIX}{session_id}"
    go.style = "PRIMARY"
    stop = msg.action_items.add()
    stop.label = iface_("Start fresh")
    stop.value = DISMISS_ACTION
    stop.style = "DEFAULT"
    _redraw()


def remove_notice(scene) -> None:
    if scene is None or not hasattr(scene, "mixie_chat_messages"):
        return
    stale = [i for i, m in enumerate(scene.mixie_chat_messages)
             if getattr(m, "bubble_id", "").startswith(BUBBLE_PREFIX)]
    for index in reversed(stale):
        scene.mixie_chat_messages.remove(index)
    _redraw()


def continue_deferred(scene_name: str) -> None:
    """Continue on the next tick (never inside the bubble's click handler)."""
    def _run():
        scene = bpy.data.scenes.get(scene_name)
        if scene is None:
            return None
        from mixar.modules.space_mixie_chat.core.parked_resume import send_continue
        if send_continue(scene, text=CONTINUE_TEXT):
            remove_notice(scene)
        else:
            _report(rpt_("The agent can continue once Mixar is connected and the chat is idle. "
                         "Press Continue again then."))
        return None

    bpy.app.timers.register(_run, first_interval=0.05)


def _redraw() -> None:
    try:
        from mixar.modules.space_mixie_chat.core.ui_utils import redraw_chat_areas
        redraw_chat_areas()
    except Exception:  # noqa: BLE001
        pass


# =============================================================================
# Registration
# =============================================================================

def recovery_root() -> str:
    """Per profile, beside Mixar's other user data (``DATAFILES/mixar``): a
    second profile (or a QA instance) never offers another's work."""
    try:
        path = bpy.utils.user_resource('DATAFILES', path="mixar/recovery", create=True)
        if isinstance(path, str) and path:
            return path
    except Exception:  # noqa: BLE001
        pass
    return journal.recovery_root()


def register() -> None:
    if not enabled() or _state["journal"] is not None:
        return
    root = recovery_root()
    os.makedirs(root, exist_ok=True)
    try:
        journal.prune(root, _now())
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[RECOVERY] prune skipped: {e}")
    # Read the earlier launches BEFORE this one's journal exists.
    try:
        _state["offer"] = _find_offer(root)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[RECOVERY] crash scan failed: {e}")
        _state["offer"] = None
    try:
        version = getattr(bpy.app, "version_string", "") or ""
        _state["journal"] = journal.Journal(root, os.getpid(), app_version=version, now=_now())
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[RECOVERY] journal unavailable, save points off: {e}")
        return
    scheduler = SavePointScheduler()
    scheduler.reset(_mono())
    _state["scheduler"] = scheduler
    handlers = bpy.app.handlers
    if _on_depsgraph_update not in handlers.depsgraph_update_post:
        handlers.depsgraph_update_post.append(_on_depsgraph_update)
    if _on_save_post not in handlers.save_post:
        handlers.save_post.append(_on_save_post)
    if _on_load_post not in handlers.load_post:
        handlers.load_post.append(_on_load_post)
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=TICK_S, persistent=True)
    atexit.register(_on_exit)
    offer = current_offer()
    if offer is not None:
        logger.info(f"[RECOVERY] crashed session {offer.get('session')} offered: "
                    f"{offer['target']['kind']} at {offer['target']['at']:.0f} "
                    f"(loop={offer.get('loop')})")
        bpy.app.timers.register(_prompt_tick, first_interval=1.0)
    elif _state["offer"] and _state["offer"].get("debris"):
        _resolve_dirs(_state["offer"]["debris"], "nothing_to_restore")


def unregister() -> None:
    handlers = bpy.app.handlers
    for hook, fn in ((handlers.depsgraph_update_post, _on_depsgraph_update),
                     (handlers.save_post, _on_save_post), (handlers.load_post, _on_load_post)):
        while fn in hook:
            hook.remove(fn)
    for fn in (_tick, _prompt_tick):
        if bpy.app.timers.is_registered(fn):
            bpy.app.timers.unregister(fn)
