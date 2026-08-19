# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""llm.request relay: POST-only, private-host allowlist, approved-base
matching, header filtering both directions, byte caps, passthrough."""

import io
import socket
import urllib.error

import pytest

from mixar.modules.local_models.core import relay

URL = "http://127.0.0.1:11500/v1/chat/completions"


@pytest.fixture(autouse=True)
def approved_base():
    relay.set_approved_bases(["http://127.0.0.1:11500"])
    yield
    relay.set_approved_bases([])


class FakeResponse:
    def __init__(self, body=b"{}", status=200, headers=None):
        self._body = body
        self.status = status
        self.headers = headers if headers is not None else {"Content-Type": "application/json"}

    def read(self, n=-1):
        data = self._body if n in (-1, None) else self._body[:n]
        self._body = b"" if n in (-1, None) else self._body[len(data):]
        return data

    def getcode(self):
        return self.status

    def close(self):
        pass


def run(params, monkeypatch=None, opener=None):
    if opener is not None:
        monkeypatch.setattr(relay, "_urlopen", opener)
    results = []
    relay.handle_llm_request(params, results.append)
    assert len(results) == 1
    return results[0]


def post(url=URL, headers=None, body='{"messages": []}'):
    return {"method": "POST", "url": url, "headers": headers or {}, "body": body}


def test_derived_base_urls():
    relay.set_approved_bases([
        "http://127.0.0.1:11500",
        "http://127.0.0.1:11434/v1",
        "http://localhost:8080/",
    ])
    assert relay.get_approved_bases() == (
        "http://127.0.0.1:11500/v1/chat/completions",
        "http://127.0.0.1:11434/v1/chat/completions",
        "http://localhost:8080/v1/chat/completions",
    )


def test_only_post_allowed():
    for method in ("GET", "PUT", "DELETE", "", None):
        result = run({"method": method, "url": URL, "headers": {}, "body": ""})
        assert result["error"]["code"] == "relay_denied"


def test_public_ip_rejected():
    result = run(post(url="http://8.8.8.8:11500/v1/chat/completions"))
    assert result["error"]["code"] == "relay_denied"


def test_link_local_metadata_ip_rejected():
    result = run(post(url="http://169.254.169.254/v1/chat/completions"))
    assert result["error"]["code"] == "relay_denied"


def test_hostname_resolving_public_rejected(monkeypatch):
    monkeypatch.setattr(
        relay, "_getaddrinfo",
        lambda host, port, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ],
    )
    result = run(post(url="http://evil.example:11500/v1/chat/completions"))
    assert result["error"]["code"] == "relay_denied"


def test_hostname_with_mixed_answers_rejected(monkeypatch):
    """EVERY resolved address must be private — one public answer kills it."""
    monkeypatch.setattr(
        relay, "_getaddrinfo",
        lambda host, port, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.2.3.4", port)),
        ],
    )
    result = run(post(url="http://rebind.example:11500/v1/chat/completions"))
    assert result["error"]["code"] == "relay_denied"


def test_hostname_resolving_private_and_approved_allowed(monkeypatch):
    relay.set_approved_bases(["http://myhost.local:11500"])
    monkeypatch.setattr(
        relay, "_getaddrinfo",
        lambda host, port, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.20", port)),
        ],
    )
    result = run(
        post(url="http://myhost.local:11500/v1/chat/completions"),
        monkeypatch, lambda req, timeout: FakeResponse(b'{"ok":1}'),
    )
    assert result["status_code"] == 200
    assert result["body"] == '{"ok":1}'


def test_private_but_unapproved_base_rejected(monkeypatch):
    monkeypatch.setattr(
        relay, "_getaddrinfo",
        lambda host, port, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port)),
        ],
    )
    result = run(post(url="http://other.local:11500/v1/chat/completions"))
    assert result["error"]["code"] == "relay_denied"


def test_wrong_path_on_approved_host_rejected():
    result = run(post(url="http://127.0.0.1:11500/v1/completions"))
    assert result["error"]["code"] == "relay_denied"
    result = run(post(url="http://127.0.0.1:11500/v1/chat/completions/extra"))
    assert result["error"]["code"] == "relay_denied"


def test_wrong_port_rejected():
    result = run(post(url="http://127.0.0.1:11501/v1/chat/completions"))
    assert result["error"]["code"] == "relay_denied"


def test_request_headers_filtered(monkeypatch):
    captured = {}

    def opener(req, timeout):
        captured["headers"] = {k.lower(): v for k, v in req.header_items()}
        return FakeResponse()

    result = run(
        post(headers={
            "Authorization": "Bearer token",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "X-Forwarded-For": "1.2.3.4",
            "Cookie": "session=1",
        }),
        monkeypatch, opener,
    )
    assert result["status_code"] == 200
    sent = captured["headers"]
    assert sent["authorization"] == "Bearer token"
    assert sent["content-type"] == "application/json"
    assert sent["accept"] == "text/event-stream"
    assert "x-forwarded-for" not in sent
    assert "cookie" not in sent


def test_response_headers_filtered(monkeypatch):
    response = FakeResponse(headers={
        "Content-Type": "application/json",
        "OpenAI-Processing-Ms": "12",
        "X-Request-Id": "abc",
        "Set-Cookie": "no",
        "Server": "llama.cpp",
    })
    result = run(post(), monkeypatch, lambda req, timeout: response)
    assert result["headers"] == {
        "content-type": "application/json",
        "openai-processing-ms": "12",
        "x-request-id": "abc",
    }


def test_request_size_cap(monkeypatch):
    monkeypatch.setattr(relay, "MAX_RELAY_REQUEST_BYTES", 100)
    result = run(post(body="x" * 101))
    assert result["error"]["code"] == "relay_request_too_large"


def test_response_size_cap(monkeypatch):
    monkeypatch.setattr(relay, "MAX_RELAY_RESPONSE_BYTES", 10)
    result = run(post(), monkeypatch, lambda req, timeout: FakeResponse(b"x" * 11))
    assert result["error"]["code"] == "relay_response_too_large"


def test_non_2xx_passes_through(monkeypatch):
    def opener(req, timeout):
        raise urllib.error.HTTPError(
            URL, 429, "Too Many Requests",
            {"Content-Type": "application/json", "Retry-After": "3"},
            io.BytesIO(b'{"error": "slow down"}'),
        )

    result = run(post(), monkeypatch, opener)
    assert result["status_code"] == 429
    assert result["body"] == '{"error": "slow down"}'
    assert result["headers"]["retry-after"] == "3"


def test_transport_failure_returns_error_marker(monkeypatch):
    def opener(req, timeout):
        raise urllib.error.URLError(ConnectionRefusedError(61, "refused"))

    result = run(post(), monkeypatch, opener)
    assert result["error"]["code"] == "relay_transport"


def test_ipv6_ula_allowed_loopback_and_scheme_rules():
    relay.set_approved_bases(["http://[fd12:3456::1]:11500"])
    assert relay._addr_allowed("::1")
    assert relay._addr_allowed("fd12:3456::1")
    assert not relay._addr_allowed("fe80::1")   # link-local
    assert not relay._addr_allowed("2001:db8::1")  # public
    result = run(post(url="ftp://127.0.0.1:11500/v1/chat/completions"))
    assert result["error"]["code"] == "relay_denied"


def test_redirects_are_never_followed():
    """The module-level opener must refuse redirects: a 3xx from the local
    server surfaces as a plain non-2xx result (Location stripped), and is
    never fetched."""
    import urllib.request

    # The opener chain must not contain a redirect-following handler
    # behaviour: _RefuseRedirects.redirect_request always returns None.
    handler = relay._RefuseRedirects()
    assert handler.redirect_request(None, None, 302, "Found", {}, "http://x") is None


def test_redirect_status_passes_through_without_location(monkeypatch):
    def opener(request, timeout=None):
        raise urllib.error.HTTPError(
            URL, 302, "Found",
            {"Location": "http://169.254.169.254/latest/meta-data/",
             "Content-Type": "text/plain"},
            io.BytesIO(b"moved"),
        )

    result = run(post(), monkeypatch, opener)
    assert result["status_code"] == 302
    assert "location" not in result["headers"]


def test_url_with_query_rejected():
    result = run(post(url=URL + "?x=http://evil"))
    assert result["error"]["code"] == "relay_denied"


def test_url_with_userinfo_rejected():
    result = run(post(url="http://user@127.0.0.1:11500/v1/chat/completions"))
    assert result["error"]["code"] == "relay_denied"


def test_malformed_port_is_denied_not_raised():
    result = run(post(url="http://127.0.0.1:1234x/v1/chat/completions"))
    assert result["error"]["code"] == "relay_denied"


def test_validate_base_url_malformed_port_returns_message():
    assert relay.validate_base_url("http://127.0.0.1:1234x") is not None


def test_dns_name_connection_pinned_to_validated_address(monkeypatch):
    """A DNS-name target is fetched via the address that passed the
    allowlist (with a Host header carrying the name) so connect-time
    re-resolution can't be rebound to a public address."""
    relay.set_approved_bases(["http://myhost.local:11500"])
    monkeypatch.setattr(
        relay, "_getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                          ("192.168.1.8", 11500))],
    )
    seen = {}

    def opener(request, timeout=None):
        seen["url"] = request.full_url
        seen["host"] = request.headers.get("Host")
        return FakeResponse()

    monkeypatch.setattr(relay, "_urlopen", opener)
    results = []
    relay.handle_llm_request(
        post(url="http://myhost.local:11500/v1/chat/completions"),
        results.append,
    )
    assert results[0]["status_code"] == 200
    assert seen["url"] == "http://192.168.1.8:11500/v1/chat/completions"
    assert seen["host"] == "myhost.local:11500"


def test_https_dns_name_refused(monkeypatch):
    relay.set_approved_bases(["https://myhost.local:11500"])
    monkeypatch.setattr(
        relay, "_getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                          ("192.168.1.8", 11500))],
    )
    result = run(post(url="https://myhost.local:11500/v1/chat/completions"))
    assert result["error"]["code"] == "relay_denied"
    assert "IP literal" in result["error"]["message"]
