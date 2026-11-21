"""Subscriptions M3, local parts: user-agent parsing, client IP behind the proxies, offline GeoIP."""
import ipaddress
import socket
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services.sessions import client_ip, geoip, user_agent

CHROME_WINDOWS = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/131.0.0.0 Safari/537.36")
EDGE_WINDOWS = CHROME_WINDOWS + " Edg/131.0.0.0"
SAFARI_IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
                 "Version/18.1 Mobile/15E148 Safari/604.1")
FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0"
CHROME_ANDROID = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/131.0.0.0 Mobile Safari/537.36")
SAFARI_MAC = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
              "Version/18.1 Safari/605.1.15")


@pytest.mark.parametrize("header, expected", [
    (CHROME_WINDOWS, ("Chrome", "Windows", "desktop")),
    (EDGE_WINDOWS, ("Edge", "Windows", "desktop")),
    (SAFARI_IPHONE, ("Safari", "iOS", "mobile")),
    (FIREFOX_LINUX, ("Firefox", "Linux", "desktop")),
    (CHROME_ANDROID, ("Chrome", "Android", "mobile")),
    (SAFARI_MAC, ("Safari", "macOS", "desktop")),
    (None, ("Unknown browser", "Unknown OS", "unknown")),
    ("curl/8.5.0", ("Unknown browser", "Unknown OS", "unknown")),
])
def test_user_agent_labels(header, expected):
    device = user_agent.parse(header)
    assert (device.browser, device.os, device.device_type) == expected


def test_user_agent_label_text():
    assert user_agent.parse(CHROME_WINDOWS).label == "Chrome on Windows"


@pytest.mark.parametrize("peer, forwarded, expected", [
    ("172.18.0.5", "41.59.10.20, 172.18.0.4", "41.59.10.20"),  # TLS nginx -> gateway -> BFF
    ("172.18.0.5", "6.6.6.6, 41.59.10.20, 172.18.0.4", "41.59.10.20"),  # a forged first entry is skipped
    ("41.59.10.20", "6.6.6.6", "41.59.10.20"),  # not behind our proxies: the header is ignored
    ("127.0.0.1", None, "127.0.0.1"),  # local development
    ("172.18.0.5", "garbage, 41.59.10.20", "41.59.10.20"),
    ("::ffff:172.18.0.5", "41.59.10.20", "41.59.10.20"),
    (None, None, None),
    (None, "41.59.10.20", None),  # no parseable peer: the header alone is never trusted
    ("testclient", "41.59.10.20", None),
])
def test_client_ip_behind_trusted_proxies(peer, forwarded, expected):
    assert client_ip.client_ip(peer, forwarded) == expected


# --- a tiny MaxMind DB writer, only for these tests -------------------------------------------------

def _encode(value) -> bytes:
    def control(kind: int, size: int) -> bytes:
        prefix = b""
        if size >= 29:
            raise AssertionError("test writer keeps sizes small")
        if kind <= 7:
            return bytes([(kind << 5) | size])
        return bytes([size, kind - 7]) + prefix

    if isinstance(value, dict):
        return control(7, len(value)) + b"".join(_encode(key) + _encode(item) for key, item in value.items())
    if isinstance(value, str):
        data = value.encode()
        return control(2, len(data)) + data
    if isinstance(value, bool):
        return control(14, int(value))
    if isinstance(value, int):
        data = value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")
        return control(6 if value < 2 ** 32 else 9, len(data)) + data
    raise TypeError(value)


def _write_mmdb(path: Path, networks: dict[str, dict], *, ip_version: int = 4) -> None:
    bits_total = 32 if ip_version == 4 else 128
    nodes: list[list[int | None]] = [[None, None]]
    data = b""
    leaves: list[tuple[int, int, int]] = []
    for network, record in networks.items():
        net = ipaddress.ip_network(network)
        offset = len(data)
        data += _encode(record)
        if ip_version == 6 and net.version == 4:
            prefix_bits, value, bits = 96 + net.prefixlen, int(net.network_address), 128
        else:
            prefix_bits, value, bits = net.prefixlen, int(net.network_address), bits_total
        node = 0
        for index in range(prefix_bits - 1):
            bit = (value >> (bits - 1 - index)) & 1
            if nodes[node][bit] is None:
                nodes.append([None, None])
                nodes[node][bit] = len(nodes) - 1
            node = nodes[node][bit]
        leaves.append((node, (value >> (bits - prefix_bits)) & 1, offset))
    count = len(nodes)
    for node, bit, offset in leaves:
        nodes[node][bit] = -(offset + 1)
    tree = b""
    for left, right in nodes:
        records = []
        for item in (left, right):
            if item is None:
                records.append(count)
            elif item < 0:
                records.append(count + 16 + (-item - 1))
            else:
                records.append(item)
        tree += records[0].to_bytes(3, "big") + records[1].to_bytes(3, "big")
    metadata = _encode({"node_count": count, "record_size": 24, "ip_version": ip_version,
                        "database_type": "Test-City", "binary_format_major_version": 2})
    path.write_bytes(tree + b"\0" * 16 + data + geoip.METADATA_MARKER + metadata)


DAR = {"city": {"names": {"en": "Dar es Salaam"}}, "country": {"iso_code": "TZ", "names": {"en": "Tanzania"}}}
NAIROBI = {"city": {"names": {"en": "Nairobi"}}, "country": {"iso_code": "KE", "names": {"en": "Kenya"}}}


@pytest.mark.parametrize("ip_version", [4, 6])
def test_geoip_reads_a_local_mmdb_file(tmp_path, ip_version):
    path = tmp_path / f"city-v{ip_version}.mmdb"
    _write_mmdb(path, {"41.59.0.0/16": DAR, "105.160.0.0/12": NAIROBI}, ip_version=ip_version)
    geoip._reader.cache_clear()
    found = geoip.lookup("41.59.10.20", str(path))
    assert (found.city, found.country, found.country_code, found.label) == (
        "Dar es Salaam", "Tanzania", "TZ", "Dar es Salaam, Tanzania")
    assert geoip.lookup("105.161.2.3", str(path)).city == "Nairobi"
    assert geoip.lookup("8.8.8.8", str(path)) is None  # not in the file
    assert geoip.lookup("192.168.1.10", str(path)) is None  # private: never looked up
    assert geoip.lookup("not-an-ip", str(path)) is None


def test_geoip_without_a_usable_file_returns_nothing(tmp_path, monkeypatch):
    geoip._reader.cache_clear()
    monkeypatch.setattr(get_settings(), "geoip_database_path", None)
    assert geoip.lookup("41.59.10.20") is None
    assert geoip.lookup("41.59.10.20", str(tmp_path / "missing.mmdb")) is None
    garbage = tmp_path / "garbage.mmdb"
    garbage.write_bytes(b"not a database" * 100)
    assert geoip.lookup("41.59.10.20", str(garbage)) is None


def test_geoip_never_opens_a_network_connection(tmp_path, monkeypatch):
    path = tmp_path / "city.mmdb"
    _write_mmdb(path, {"41.59.0.0/16": DAR})
    geoip._reader.cache_clear()

    def refuse(*_args, **_kwargs):
        raise AssertionError("GeoIP lookup tried to open a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    assert geoip.lookup("41.59.10.20", str(path)).city == "Dar es Salaam"
    source = Path(geoip.__file__).read_text()
    for forbidden in ("import socket", "import http", "import urllib", "import requests", "import httpx"):
        assert forbidden not in source


def test_geoip_decoder_handles_pointers_and_extended_sizes(tmp_path):
    # A pointer (type 1, size 0) from a map value to a string stored earlier in the data section.
    data = _encode("Arusha")
    pointer = bytes([0x20, 0x00])  # pointer to data offset 0
    record = bytes([0xE1]) + _encode("city") + pointer  # map{1}: "city" -> pointer
    decoder = geoip._Decoder(data + record, 0)
    value, _ = decoder.decode(len(data))
    assert value == {"city": "Arusha"}
    long = "x" * 40  # size 29 + 11 extra
    encoded = bytes([(2 << 5) | 29, 11]) + long.encode()
    assert geoip._Decoder(encoded, 0).decode(0)[0] == long
    assert geoip._Decoder(bytes([0x01, 0x07]), 0).decode(0)[0] is True  # extended type 14: boolean
