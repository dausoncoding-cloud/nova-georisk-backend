"""Offline, city-level IP location from a local MaxMind DB (.mmdb) file, for example DB-IP "IP to City
Lite" (CC BY 4.0: show "IP geolocation by DB-IP" next to locations).

The IP address never leaves the server: this module only reads a local file (memory-mapped). It has
no network code and no dependency. When `GEOIP_DATABASE_PATH` is unset, unreadable or not an MMDB
file, every lookup returns None and sign-in carries on without a location.

Format: https://maxmind.github.io/MaxMind-DB/ (binary search tree, then a data section; the metadata
map follows the marker at the end of the file).
"""
from __future__ import annotations

import ipaddress
import logging
import mmap
import struct
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger(__name__)

METADATA_MARKER = b"\xab\xcd\xefMaxMind.com"
_METADATA_SEARCH = 128 * 1024
_DATA_SEPARATOR = 16
_MAX_DEPTH = 32


class InvalidDatabase(ValueError):
    pass


@dataclass(frozen=True)
class Location:
    city: str | None
    country: str | None
    country_code: str | None

    @property
    def label(self) -> str | None:
        parts = [part for part in (self.city, self.country) if part]
        return ", ".join(parts) or None


class _Decoder:
    def __init__(self, buffer, base: int):
        self._buffer = buffer
        self._base = base  # offsets inside the data section are relative to this

    def decode(self, offset: int, depth: int = 0):
        if depth > _MAX_DEPTH:
            raise InvalidDatabase("Data nesting is too deep.")
        buffer = self._buffer
        control = buffer[self._base + offset]
        offset += 1
        kind = control >> 5
        if kind == 1:  # pointer
            size = (control >> 3) & 0x3
            value = control & 0x7
            raw = bytes(buffer[self._base + offset:self._base + offset + size + 1])
            if size == 0:
                pointer = (value << 8) | raw[0]
            elif size == 1:
                pointer = ((value << 16) | int.from_bytes(raw[:2], "big")) + 2048
            elif size == 2:
                pointer = ((value << 24) | int.from_bytes(raw[:3], "big")) + 526336
            else:
                pointer = int.from_bytes(raw[:4], "big")
            target, _ = self.decode(pointer, depth + 1)
            return target, offset + size + 1
        if kind == 0:  # extended type
            kind = 7 + buffer[self._base + offset]
            offset += 1
        size = control & 0x1F
        if size >= 29 and kind not in (14,):
            extra = size - 28
            raw = int.from_bytes(bytes(buffer[self._base + offset:self._base + offset + extra]), "big")
            size = (29, 285, 65821)[extra - 1] + raw
            offset += extra
        start = self._base + offset
        if kind == 2:  # utf-8 string
            return bytes(buffer[start:start + size]).decode("utf-8", "replace"), offset + size
        if kind == 3:  # double
            return struct.unpack(">d", bytes(buffer[start:start + 8]))[0], offset + 8
        if kind == 4:  # bytes
            return bytes(buffer[start:start + size]), offset + size
        if kind in (5, 6, 9, 10):  # unsigned integers
            return int.from_bytes(bytes(buffer[start:start + size]), "big"), offset + size
        if kind == 8:  # int32
            raw = bytes(buffer[start:start + size]).rjust(4, b"\0")
            return struct.unpack(">i", raw)[0], offset + size
        if kind == 7:  # map
            result = {}
            for _ in range(size):
                key, offset = self.decode(offset, depth + 1)
                result[key], offset = self.decode(offset, depth + 1)
            return result, offset
        if kind == 11:  # array
            items = []
            for _ in range(size):
                item, offset = self.decode(offset, depth + 1)
                items.append(item)
            return items, offset
        if kind == 14:  # boolean (the size is the value)
            return bool(size), offset
        if kind == 15:  # float
            return struct.unpack(">f", bytes(buffer[start:start + 4]))[0], offset + 4
        raise InvalidDatabase(f"Unsupported data type {kind}.")


class Reader:
    def __init__(self, path: str | Path):
        handle = open(path, "rb")
        try:
            self._buffer = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
        finally:
            handle.close()
        tail_start = max(0, len(self._buffer) - _METADATA_SEARCH)
        marker = self._buffer.rfind(METADATA_MARKER, tail_start)
        if marker < 0:
            raise InvalidDatabase("Not a MaxMind DB file (metadata marker missing).")
        metadata, _ = _Decoder(self._buffer, marker + len(METADATA_MARKER)).decode(0)
        try:
            self.node_count = int(metadata["node_count"])
            self.record_size = int(metadata["record_size"])
            self.ip_version = int(metadata["ip_version"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidDatabase("Incomplete MaxMind DB metadata.") from exc
        if self.record_size not in (24, 28, 32):
            raise InvalidDatabase("Unsupported record size.")
        self.database_type = metadata.get("database_type")
        self._node_bytes = self.record_size // 4
        self._tree_size = self._node_bytes * self.node_count
        self._data = _Decoder(self._buffer, self._tree_size + _DATA_SEPARATOR)
        self._ipv4_start = None

    def _record(self, node: int, bit: int) -> int:
        start = node * self._node_bytes
        raw = self._buffer[start:start + self._node_bytes]
        if self.record_size == 24:
            return int.from_bytes(raw[3:6] if bit else raw[0:3], "big")
        if self.record_size == 28:
            if bit:
                return ((raw[3] & 0x0F) << 24) | int.from_bytes(raw[4:7], "big")
            return ((raw[3] & 0xF0) << 20) | int.from_bytes(raw[0:3], "big")
        return int.from_bytes(raw[4:8] if bit else raw[0:4], "big")

    def _start_node(self, address) -> tuple[int, int]:
        if self.ip_version == 4:
            if address.version == 6:
                raise ValueError("IPv6 address in an IPv4-only database.")
            return 0, 32
        if address.version == 6:
            return 0, 128
        if self._ipv4_start is None:  # IPv4 lives under ::/96 in an IPv6 tree
            node = 0
            for _ in range(96):
                if node >= self.node_count:
                    break
                node = self._record(node, 0)
            self._ipv4_start = node
        return self._ipv4_start, 32

    def get(self, ip: str) -> dict | None:
        address = ipaddress.ip_address(ip)
        if address.version == 6 and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        node, bits = self._start_node(address)
        value = int(address)
        for index in range(bits):
            if node >= self.node_count:
                break
            node = self._record(node, (value >> (bits - 1 - index)) & 1)
        if node == self.node_count:
            return None
        if node < self.node_count:
            raise InvalidDatabase("Search tree is malformed.")
        offset = node - self.node_count - _DATA_SEPARATOR
        record, _ = self._data.decode(offset)
        return record if isinstance(record, dict) else None


def _name(section) -> str | None:
    if not isinstance(section, dict):
        return None
    names = section.get("names")
    if isinstance(names, dict):
        value = names.get("en") or next(iter(names.values()), None)
        return str(value)[:128] if value else None
    return None


@lru_cache(maxsize=4)
def _reader(path: str) -> Reader | None:
    try:
        return Reader(path)
    except (OSError, ValueError, InvalidDatabase, KeyError, IndexError):
        logger.warning("GeoIP database could not be opened; locations are disabled.")
        return None


def lookup(ip: str | None, path: str | None = None) -> Location | None:
    """City and country for an IP, or None (private address, no file, not found, any error)."""
    path = path if path is not None else get_settings().geoip_database_path
    if not ip or not path or not Path(path).is_file():
        return None
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if not address.is_global:
        return None
    reader = _reader(str(path))
    if reader is None:
        return None
    try:
        record = reader.get(str(address))
    except (ValueError, InvalidDatabase, IndexError, struct.error, UnicodeDecodeError):
        return None
    if not record:
        return None
    country = record.get("country") if isinstance(record.get("country"), dict) else {}
    code = country.get("iso_code")
    location = Location(city=_name(record.get("city")), country=_name(country),
                        country_code=str(code)[:2] if code else None)
    return location if (location.city or location.country) else None
