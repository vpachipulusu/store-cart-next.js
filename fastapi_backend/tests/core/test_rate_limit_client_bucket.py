"""Client keys group IPv6 addresses by /64 (KAN-252); IPv4 is unchanged."""

import pytest
from starlette.requests import Request

from app.api.rate_limit import client_ip, client_key, forwarded_client_ip
from app.core.rate_limit import client_bucket


@pytest.mark.parametrize(
    ("address", "bucket"),
    [
        ("203.0.113.7", "203.0.113.7"),
        ("2001:db8:1:2:aaaa:bbbb:cccc:dddd", "2001:db8:1:2::/64"),
        ("2001:db8:1:2::1", "2001:db8:1:2::/64"),
        ("2001:DB8:1:2:ffff:ffff:ffff:ffff", "2001:db8:1:2::/64"),
        ("::ffff:198.51.100.9", "198.51.100.9"),
        ("fe80::1%eth0", "fe80::/64"),
        ("::1", "::/64"),
    ],
)
def test_ipv6_is_grouped_by_64_and_ipv4_is_unchanged(address: str, bucket: str) -> None:
    assert client_bucket(address) == bucket


def test_addresses_in_one_64_share_a_bucket_and_other_64s_do_not() -> None:
    same = {client_bucket(f"2001:db8:5:6::{n:x}") for n in range(1, 50)}
    other = client_bucket("2001:db8:5:7::1")

    assert len(same) == 1
    assert other not in same


@pytest.mark.parametrize(
    "address", ["not-an-ip", "", "1.2.3.4.5", "2001:db8::/64", "1.2.3.4%eth0"]
)
def test_a_malformed_address_is_rejected(address: str) -> None:
    with pytest.raises(ValueError):
        client_bucket(address)


def make_request(
    *, header: str | None, internal: bool, peer: str | None = "127.0.0.1"
) -> Request:
    headers = [(b"x-client-ip", header.encode())] if header is not None else []
    scope = {
        "type": "http",
        "headers": headers,
        "client": (peer, 1234) if peer else None,
        "state": {"internal_authenticated": internal},
    }
    return Request(scope)


def test_forwarded_ipv6_client_keys_on_its_64_but_client_ip_stays_exact() -> None:
    request = make_request(header="2001:db8:9:9:1:2:3:4", internal=True)

    assert client_key(request) == "2001:db8:9:9::/64"
    assert client_ip(request) == "2001:db8:9:9:1:2:3:4"
    assert forwarded_client_ip(request) == "2001:db8:9:9:1:2:3:4"


def test_forwarded_ipv4_client_is_unchanged() -> None:
    request = make_request(header="203.0.113.7", internal=True)

    assert client_key(request) == client_ip(request) == "203.0.113.7"


def test_an_untrusted_header_is_ignored_and_the_ipv6_peer_is_grouped() -> None:
    request = make_request(
        header="9.9.9.9", internal=False, peer="2001:db8:a:b:c:d:e:f"
    )

    assert client_key(request) == "2001:db8:a:b::/64"
    assert client_ip(request) == "2001:db8:a:b:c:d:e:f"
    assert forwarded_client_ip(request) is None


def test_a_malformed_header_falls_back_to_the_peer_and_an_unknown_peer_stays_unknown() -> (
    None
):
    bad = make_request(header="nope", internal=True, peer="127.0.0.1")
    no_peer = make_request(header=None, internal=True, peer=None)

    assert client_key(bad) == "127.0.0.1"
    assert client_key(no_peer) == "unknown"
