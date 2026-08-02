"""Tests for demo_protection.py's trusted-proxy client-IP resolution —
operational-hardening prompt 2, requirement 5. `_client_ip` only reads
`request.headers`/`request.client.host`, so a minimal stub standing in
for a real Starlette Request is enough to unit-test the resolution logic
in isolation, without needing a full ASGI scope. Store-error/telemetry
behaviour and the end-to-end 429 path are covered at the API level in
test_demo.py; this file is specifically about "which IP string does
this resolve to.\""""

import pytest

import app.demo_protection as demo_protection
from app.demo_protection import _client_ip


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    def __init__(self, client_host, headers=None):
        self.client = _FakeClient(client_host) if client_host is not None else None
        self.headers = headers or {}


@pytest.fixture(autouse=True)
def _default_trust_zero(monkeypatch):
    """Every test starts from the safe default (trust nothing) unless it
    explicitly opts in — mirrors the module's own default."""
    monkeypatch.setattr(demo_protection, "TRUSTED_PROXY_HOP_COUNT", 0)


def test_defaults_to_socket_peer_when_no_proxy_trusted():
    request = _FakeRequest("203.0.113.9", headers={"x-forwarded-for": "198.51.100.1"})
    assert _client_ip(request) == "203.0.113.9"


def test_ignores_x_forwarded_for_when_hop_count_is_zero():
    """The anti-spoofing default: an attacker-supplied XFF header must
    never override the real socket peer unless an operator has
    explicitly configured how many proxy hops to trust."""
    request = _FakeRequest("203.0.113.9", headers={"x-forwarded-for": "1.2.3.4, 5.6.7.8"})
    assert _client_ip(request) == "203.0.113.9"


def test_uses_xff_when_a_single_trusted_hop_is_configured(monkeypatch):
    monkeypatch.setattr(demo_protection, "TRUSTED_PROXY_HOP_COUNT", 1)
    # the proxy's own socket peer (its internal address) is irrelevant
    # once XFF is trusted — the real client is the rightmost XFF entry
    request = _FakeRequest("10.0.0.1", headers={"x-forwarded-for": "203.0.113.9"})
    assert _client_ip(request) == "203.0.113.9"


def test_uses_correct_hop_for_multi_hop_xff(monkeypatch):
    """Two trusted proxies: the header accumulates left-to-right, each
    hop appending what it saw — the real client is the leftmost of the
    two trusted entries (second-from-right for hop_count=2)."""
    monkeypatch.setattr(demo_protection, "TRUSTED_PROXY_HOP_COUNT", 2)
    request = _FakeRequest("10.0.0.2", headers={"x-forwarded-for": "203.0.113.9, 10.0.0.1"})
    assert _client_ip(request) == "203.0.113.9"


def test_falls_back_to_socket_peer_when_xff_has_fewer_hops_than_configured(monkeypatch):
    """Malformed/short header: don't guess, fall back to the raw socket
    peer — same safe-default direction as trusting nothing at all."""
    monkeypatch.setattr(demo_protection, "TRUSTED_PROXY_HOP_COUNT", 2)
    request = _FakeRequest("10.0.0.1", headers={"x-forwarded-for": "203.0.113.9"})
    assert _client_ip(request) == "10.0.0.1"


def test_falls_back_when_xff_header_is_entirely_missing(monkeypatch):
    monkeypatch.setattr(demo_protection, "TRUSTED_PROXY_HOP_COUNT", 1)
    request = _FakeRequest("10.0.0.1", headers={})
    assert _client_ip(request) == "10.0.0.1"


def test_falls_back_when_xff_is_empty_or_whitespace_only(monkeypatch):
    monkeypatch.setattr(demo_protection, "TRUSTED_PROXY_HOP_COUNT", 1)
    for xff in ("", "   ", ",,,"):
        request = _FakeRequest("10.0.0.1", headers={"x-forwarded-for": xff})
        assert _client_ip(request) == "10.0.0.1"


def test_tolerates_extra_whitespace_and_empty_segments_in_xff(monkeypatch):
    monkeypatch.setattr(demo_protection, "TRUSTED_PROXY_HOP_COUNT", 1)
    request = _FakeRequest("10.0.0.1", headers={"x-forwarded-for": "  203.0.113.9  ,  , 10.0.0.2  "})
    assert _client_ip(request) == "10.0.0.2"


def test_handles_ipv6_socket_peer():
    request = _FakeRequest("2001:db8::1")
    assert _client_ip(request) == "2001:db8::1"


def test_handles_ipv6_addresses_in_xff(monkeypatch):
    monkeypatch.setattr(demo_protection, "TRUSTED_PROXY_HOP_COUNT", 1)
    request = _FakeRequest("::1", headers={"x-forwarded-for": "2001:db8::1"})
    assert _client_ip(request) == "2001:db8::1"


def test_handles_mixed_ipv4_and_ipv6_hops_in_xff(monkeypatch):
    monkeypatch.setattr(demo_protection, "TRUSTED_PROXY_HOP_COUNT", 2)
    request = _FakeRequest("::1", headers={"x-forwarded-for": "2001:db8::1, 203.0.113.9"})
    assert _client_ip(request) == "2001:db8::1"


def test_returns_unknown_when_no_client_info_at_all():
    request = _FakeRequest(None)
    assert _client_ip(request) == "unknown"
