# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The crash scrubber: no local path, user name, e-mail or prompt leaves the machine."""

import pytest

from mixar.modules.common.crash_reports.core import scrub
from mixar.modules.common.crash_reports.core.scrub import (
    python_file,
    scrub_crash_text,
    scrub_report_line,
    scrub_text,
)

NO_NAMES = ()


@pytest.mark.parametrize(("raw", "expected"), [
    # Windows: drive paths with spaces, either slash, and Python's escaped form.
    (r"C:\Users\Jane Smith\AppData\Local\Temp\mixar.crash.txt", r"<path>\mixar.crash.txt"),
    (r"D:\Client Work\Final Renders\shot 010.png", r"<path>\shot 010.png"),
    ("C:/Program Files/Mixar/Mixar.exe", r"<path>\Mixar.exe"),
    (r'filepath="C:\\Users\\Jane Smith\\Docs\\castle.blend"', r'filepath="<path>\<file>.blend"'),
    # UNC shares, including a hidden ($) share and spaces.
    (r"\\fileserver\home$\Jane Smith\Mixar\notes.txt", r"<path>\notes.txt"),
    (r"open \\nas01\projects\Acme Corp\brief.pdf now", r"open <path>\brief.pdf now"),
    # POSIX homes and temp dirs.
    ("/Users/jdoe/Library/Application Support/Mixar/x.py", "<path>/x.py"),
    ("/home/jane doe/.config/mixar/log.txt", "<path>/log.txt"),
    ("/var/folders/h5/k8z_x/T/mixar.crash.txt", "<path>/mixar.crash.txt"),
    # Home-relative.
    ("~/Projects/Client X/notes.txt", "<path>/notes.txt"),
    (r"~\Documents\Client X\notes.txt", r"<path>/notes.txt"),
    # E-mails.
    ("mail jane.doe+mixar@example.co.uk now", "mail <email> now"),
    ("JDOE@Example.COM", "<email>"),
    # Project file names are user content.
    ("/Users/jdoe/Desktop/My Secret Scene.blend", "<path>/My Secret <file>.blend"),
    ("pear_123_autosave.mixar", "<file>.mixar"),
])
def test_scrub_text_paths_and_emails(raw, expected):
    assert scrub_text(raw, NO_NAMES) == expected


def test_user_name_is_removed_wherever_it_remains():
    text = "user jdoe ran Mixar; owner=JDoe; jdoe_backup stays"
    assert scrub_text(text, ("jdoe",)) == "user <user> ran Mixar; owner=<user>; jdoe_backup stays"


def test_local_user_names_come_from_the_os(monkeypatch):
    monkeypatch.setattr(scrub, "_cached_names", None)
    monkeypatch.setattr(scrub.getpass, "getuser", lambda: "janesmith")
    monkeypatch.setattr(scrub.os.path, "expanduser", lambda _: "/Users/jane.smith")
    assert scrub.local_user_names() == ("jane.smith", "janesmith")
    assert scrub_text("hello janesmith and jane.smith") == "hello <user> and <user>"
    monkeypatch.setattr(scrub, "_cached_names", None)


def test_urls_and_symbols_are_kept():
    url = "https://developers.cloudflare.com/support/troubleshooting/"
    frame = "3   Mixar   0x000000010568127c _ZN7blender22DEG_id_type_any_existsEPKNS_9DepsgraphEs + 24"
    assert scrub_text(url, NO_NAMES) == url
    assert scrub_text(frame, NO_NAMES) == frame


@pytest.mark.parametrize(("line", "expected"), [
    ('bpy.context.scene.mixie_chat_input = "make a logo for ACME"  # Property',
     "bpy.context.scene.mixie_chat_input = <redacted>  # Property"),
    ('bpy.context.scene.mixie_moodboard_action_nodes[0].prompt = "x"  # Property',
     "bpy.context.scene.mixie_moodboard_action_nodes[].prompt = <redacted>  # Property"),
    ('bpy.ops.import_scene.gltf(filepath="/Users/jdoe/x.glb", loglevel=20)  # Operator',
     "bpy.ops.import_scene.gltf()  # Operator"),
    ("Batch 1 failed (524): {'zone': 'api.example.com'}  # Warning", None),
    ("Created Model 3D node  # Info", None),
])
def test_report_log_lines_lose_their_content(line, expected):
    assert scrub_report_line(line) == expected


@pytest.mark.parametrize(("path", "expected"), [
    ("/Users/jdoe/Library/Application Support/Mixar/4.3/scripts/mixar/modules/a/core/b.py",
     "mixar/modules/a/core/b.py"),
    (r"C:\Program Files\Mixar\4.3\scripts\mixar\modules\a\b.py", "mixar/modules/a/b.py"),
    (r"\\fileserver\home$\Jane\scripts\startup\bl_ui\space_topbar.py", "startup/bl_ui/space_topbar.py"),
    ("/Users/jdoe/.venv/lib/python3.13/site-packages/requests/api.py", "requests/api.py"),
    ("/Users/jdoe/scratch/variants2.py", "variants2.py"),
    ("<frozen importlib._bootstrap>", "<frozen importlib._bootstrap>"),
])
def test_python_file_keeps_only_the_in_app_part(path, expected):
    assert python_file(path) == expected


def test_scrub_crash_text_on_a_real_crash_log(fixture_text):
    raw = fixture_text("macos_render.crash.txt")
    scrubbed = scrub_crash_text(raw, ("jdoe",))
    assert "jdoe" not in scrubbed.lower()
    assert "Sample prompt" not in scrubbed and "@example.com" not in scrubbed
    assert "/Users/" not in scrubbed and "/Library/" not in scrubbed
    assert "bpy.ops.mixie_chat.send_message()  # Operator" in scrubbed
    assert "_ZN7blender22DEG_id_type_any_existsEPKNS_9DepsgraphEs + 24" in scrubbed
    assert "Error 524" not in scrubbed  # Warning lines are dropped


def test_scrub_crash_text_on_a_windows_log(fixture_text):
    scrubbed = scrub_crash_text(fixture_text("windows_access_violation.crash.txt"), NO_NAMES)
    for leaked in ("Jane Smith", "Client Work", "castle", "jane.smith@", "fileserver", "Program Files"):
        assert leaked not in scrubbed
    assert "EXCEPTION_ACCESS_VIOLATION" in scrubbed and "nvoglv64.dll" in scrubbed
