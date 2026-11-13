# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Whose Update Result Is This? (#2079)

On Windows the next start reads a helper's result from every staging folder
(``staging.result_dirs``): the update that moved Mixar out of Program Files
was run by the old app's helper, which wrote it under ``%ProgramData%``.
That folder is shared by every account on the computer, and another
account's Program Files Mixar writes its own results there. Reading one
would report (and delete) that account's attempt as this user's.

So a result outside this copy's own staging folder is read only when it
names an attempt this user's helper ran (:func:`remember_attempt`, kept in
the per-user config), or at the first start after the move, once per
install folder: the old app's attempt id is not known to the moved copy.
Nothing here needs ``bpy``.
"""

import ntpath

from mixar.config.logging_config import get_logger

from ..constants import (
    MOVE_RESULT_READ_CONFIG_KEY,
    UPDATE_ATTEMPTS_CONFIG_KEY,
    UPDATE_ATTEMPTS_KEPT,
)

logger = get_logger(__name__)


def _config() -> dict:
    from mixar.config.config import get_config

    return get_config()


def _add_config(key, value) -> None:
    from mixar.config.config import add_config

    add_config(key, value)


def _moved_from() -> str:
    from .win_scope import moved_from

    return moved_from()


def remember_attempt(attempt_id) -> None:
    """This user's helper runs *attempt_id*. Never raises."""
    if not attempt_id:
        return
    try:
        attempts = [a for a in (_config().get(UPDATE_ATTEMPTS_CONFIG_KEY) or [])
                    if isinstance(a, str) and a != attempt_id]
        attempts.append(attempt_id)
        _add_config(UPDATE_ATTEMPTS_CONFIG_KEY, attempts[-UPDATE_ATTEMPTS_KEPT:])
    except Exception:  # noqa: BLE001 - only narrows which results are read
        logger.debug("Could not record the update attempt", exc_info=True)


def own_attempt(attempt_id) -> bool:
    try:
        return bool(attempt_id) and attempt_id in (
            _config().get(UPDATE_ATTEMPTS_CONFIG_KEY) or [])
    except Exception:  # noqa: BLE001
        return False


def first_start_after_move(install_dir, moved_from, read_for) -> bool:
    """Pure: an install moved into *install_dir* (from *moved_from*) whose
    first start has not read the shared result yet (*read_for*)."""
    if not moved_from or not install_dir:
        return False
    return ntpath.normcase(str(read_for or "")) != ntpath.normcase(install_dir)


def foreign_filter(install_dir):
    """``accept(result)`` for results outside this copy's staging folder.

    Using it spends the first-start-after-the-move window for
    *install_dir*: later starts read only their own attempts there.
    """
    try:
        first = first_start_after_move(
            install_dir, _moved_from(), _config().get(MOVE_RESULT_READ_CONFIG_KEY))
        if first:
            _add_config(MOVE_RESULT_READ_CONFIG_KEY, install_dir)
    except Exception:  # noqa: BLE001 - read only our own attempts then
        logger.debug("Could not tell whether this is the first start after the move",
                     exc_info=True)
        first = False

    def accept(result) -> bool:
        if own_attempt(result.get("attempt_id")):
            return True
        if first:
            return True
        logger.info("Leaving an update result of another account (attempt %s) unread",
                    result.get("attempt_id") or "?")
        return False

    return accept
