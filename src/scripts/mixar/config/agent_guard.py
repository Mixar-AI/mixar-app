# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Is an agent script on the call stack?

Agent scripts are compiled as ``<agent_script>`` and run beneath
``space_mixie_chat/core/executor.py``; a timer or handler a script
registered still runs a ``<agent_script>`` frame. Used to refuse actions
that only the user may take (config redirects, public publishes).
"""

import os
import sys

AGENT_SCRIPT_FILENAME = "<agent_script>"
_EXECUTOR_FILES = (os.path.join("space_mixie_chat", "core", "executor.py"),)


def called_from_agent_script() -> bool:
    frame = sys._getframe(1)
    while frame is not None:
        name = frame.f_code.co_filename
        if name == AGENT_SCRIPT_FILENAME or name.endswith(_EXECUTOR_FILES):
            return True
        frame = frame.f_back
    return False
