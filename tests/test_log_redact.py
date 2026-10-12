# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Secrets never reach the client log file or a support bundle."""

import logging

import pytest

from mixar.config import logging_config
from mixar.config.log_redact import REDACTED, redact_text

LEAKS = {
    # requests exception text for an expired presigned GLB URL.
    "presigned": ("403 Client Error: Forbidden for url: https://b.s3.amazonaws.com/k.glb"
                  "?X-Amz-Algorithm=AWS4&X-Amz-Credential=AKIAXYZ%2F2026&X-Amz-Signature=abcdef0123"),
    # FastAPI 422 detail list echoing the BYOK request body.
    "pydantic": ("[{'type': 'string_too_long', 'loc': ('body', 'api_key'), "
                 "'input': 'sk-ant-api03-SECRETSECRETSECRET'}]"),
    "pydantic_dict": "[{'type': 'missing', 'input': {'provider': 'x', 'password': 'hunter22'}}]",
    "bearer": "headers={'Authorization': 'Bearer abc.def-ghi_jkl'}",
    "jwt": "refresh with eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJlMTIz failed",
    "handoff": "Failed to open https://www.mixar.app/auth/handoff?ticket=tkt_9f8e7d6c5b",
    "gemini": "key AIzaSyA1234567890abcdefghijklmnop rejected",
    "groq": "gsk_ABCDEFGHIJKLMNOP1234 invalid",
    "json": '{"access_token": "opaque-token-value", "refresh_token": "r-123456"}',
}
SECRETS = ("AKIAXYZ", "abcdef0123", "SECRETSECRET", "hunter22", "abc.def-ghi_jkl",
           "eyJhbGciOiJIUzI1NiJ9", "tkt_9f8e7d6c5b", "AIzaSyA1234567890", "gsk_ABCDEF",
           "opaque-token-value", "r-123456")


@pytest.mark.parametrize("name", sorted(LEAKS))
def test_known_leak_shapes_are_redacted(name):
    out = redact_text(LEAKS[name])
    assert REDACTED in out
    assert not any(secret in out for secret in SECRETS), out


def test_ordinary_lines_are_left_alone():
    line = "Generated 3 meshes in 4.2 s; max_token=4096; scene=Kitchen.001 objects=12"
    assert redact_text(line) == line


def test_the_log_file_is_redacted_on_write(tmp_path, monkeypatch):
    monkeypatch.setenv("MIXAR_CLIENT_LOG_DIR", str(tmp_path))
    logging_config.reset_file_handler()
    try:
        logger = logging_config.get_logger("mixar.redact.test", level=logging.ERROR)
        logger.warning("download failed: %s", LEAKS["presigned"])
        try:
            raise RuntimeError(LEAKS["pydantic"])
        except RuntimeError:
            logger.error("save failed", exc_info=True)
        logging_config.get_file_handler().flush()
        text = (tmp_path / logging_config.LOG_FILENAME).read_text(encoding="utf-8")
    finally:
        logging_config.reset_file_handler()
    assert "download failed" in text and "save failed" in text
    assert "abcdef0123" not in text and "SECRETSECRET" not in text
