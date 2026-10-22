# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Both native composer variants retain local text undo, not document undo."""
from pathlib import Path
import re


def test_empty_and_transcript_composers_do_not_push_document_undo():
    source = (Path(__file__).parents[1] /
              'src/source/blender/editors/space_agent_bubble/space_agent_bubble.cc').read_text()
    fields = re.findall(r'ui::Button \*input_but = uiDefButR\(.*?\n    [ ]*}', source, re.S)
    assert len(fields) == 2
    for field in fields:
        assert '"mixie_chat_input"' in field
        assert 'ui::button_flag_enable(input_but, ui::BUT_TEXTEDIT_UPDATE)' in field
        assert 'ui::button_flag_disable(input_but, ui::BUT_UNDO)' in field
