# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.connector.core.protocol import (  # noqa: E402
    is_loopback_url,
    parse_export_body,
    request_rejection,
    sidecar_routes,
)


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


class _Headers(dict):
    """The subset of ``email.message.Message`` the admission check reads."""


def _headers(port, token=None, **extra):
    headers = _Headers({"Host": "127.0.0.1:%d" % port})
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    headers.update(extra)
    return headers


def test_request_admission_requires_host_token_and_no_origin():
    token = "t" * 43
    assert request_rejection(_headers(7733, token), 7733, token) is None
    assert request_rejection(_headers(7733), 7733, token)[0] == 401
    assert request_rejection(_headers(7733, "u" * 43), 7733, token)[0] == 401
    assert request_rejection(_headers(7733, token, Origin="https://example.com"), 7733, token)[0] == 403
    assert request_rejection(_headers(7733, token, Origin="null"), 7733, token)[0] == 403
    rebound = _headers(7733, token)
    rebound["Host"] = "localhost:7733"
    assert request_rejection(rebound, 7733, token)[0] == 403
    assert request_rejection(_headers(7734, token), 7733, token)[0] == 403


def test_request_admission_never_passes_with_an_empty_token():
    assert request_rejection(_headers(7733, ""), 7733, "")[0] == 401


def test_request_admission_rejects_a_non_ascii_credential_quietly():
    # A latin-1 decoded header must be a plain 401, not a TypeError.
    assert request_rejection(_headers(7733, "tok\xe9n"), 7733, "t" * 43)[0] == 401


def test_sidecar_offers_no_cross_origin_route():
    assert "OPTIONS" not in sidecar_routes()
