# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.connector.core.protocol import is_loopback_url, parse_export_body  # noqa: E402


def test_parse_export_normalizes_usd_variants():
    spec = parse_export_body('{"format": "usda", "destination": "unreal"}')
    assert spec["format"] == "usd"
    assert spec["destination"] == "unreal"
    assert spec["actor_label"] == "MixarScene"


def test_parse_export_rejects_unknown_format():
    try:
        parse_export_body('{"format": "obj"}')
    except ValueError as exc:
        assert "unsupported format" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_sidecar_must_stay_on_loopback():
    assert is_loopback_url("http://127.0.0.1:7733/health")
    assert is_loopback_url("http://localhost:7734")
    assert not is_loopback_url("http://unreal.example:8000/mcp")
