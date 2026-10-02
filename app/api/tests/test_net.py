from starlette.requests import Request

from amber.util.config import Settings
from amber.util.net import client_ip


def _request(peer: str, xff: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


TRUSTING = Settings(env="test", trusted_proxies="10.0.0.0/8, 130.211.0.0/22")


def test_untrusted_peer_is_the_client_and_its_header_is_ignored():
    assert client_ip(_request("203.0.113.9", xff="1.2.3.4"), TRUSTING) == "203.0.113.9"


def test_trusted_proxy_reports_the_client():
    assert client_ip(_request("130.211.0.5", xff="198.51.100.7"), TRUSTING) == "198.51.100.7"


def test_client_supplied_entries_are_ignored():
    # The client sent "X-Forwarded-For: 6.6.6.6"; the LB appended the real address.
    assert client_ip(_request("130.211.0.5", xff="6.6.6.6, 198.51.100.7"), TRUSTING) == "198.51.100.7"


def test_chained_trusted_proxies_are_skipped():
    assert client_ip(_request("10.0.0.2", xff="198.51.100.7, 130.211.0.5"), TRUSTING) == "198.51.100.7"


def test_no_trusted_proxies_configured_means_no_header_trust():
    assert client_ip(_request("10.0.0.2", xff="198.51.100.7"), Settings(env="test")) == "10.0.0.2"
