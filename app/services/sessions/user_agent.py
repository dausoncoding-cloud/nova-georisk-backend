"""Small local user-agent parser: browser family, operating system, device type. No lookups, no
network, no third-party list. Only these three labels are stored; the raw header is not kept."""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_HEADER = 1024


@dataclass(frozen=True)
class Device:
    browser: str
    os: str
    device_type: str  # desktop, mobile, tablet or unknown

    @property
    def label(self) -> str:
        return f"{self.browser} on {self.os}"


# Order matters: Edge, Opera and Samsung Internet also say "Chrome"; Chrome also says "Safari".
_BROWSERS = (
    ("Edge", re.compile(r"\bEdg(?:e|A|iOS)?/(\d+)")),
    ("Opera", re.compile(r"\b(?:OPR|Opera)/(\d+)")),
    ("Samsung Internet", re.compile(r"\bSamsungBrowser/(\d+)")),
    ("Firefox", re.compile(r"\b(?:Firefox|FxiOS)/(\d+)")),
    ("Chrome", re.compile(r"\b(?:Chrome|CriOS)/(\d+)")),
    ("Safari", re.compile(r"\bVersion/(\d+)[.\d]* (?:Mobile/\S+ )?Safari/")),
)
_OSES = (
    ("iOS", re.compile(r"\b(?:iPhone|iPad|iPod)\b")),
    ("Android", re.compile(r"\bAndroid\b")),
    ("Windows", re.compile(r"\bWindows\b")),
    ("ChromeOS", re.compile(r"\bCrOS\b")),
    ("macOS", re.compile(r"\bMac OS X\b|\bMacintosh\b")),
    ("Linux", re.compile(r"\bLinux\b")),
)


def parse(header: str | None) -> Device:
    value = (header or "")[:MAX_HEADER]
    browser = next((name for name, pattern in _BROWSERS if pattern.search(value)), "Unknown browser")
    os = next((name for name, pattern in _OSES if pattern.search(value)), "Unknown OS")
    if re.search(r"\biPad\b|\bTablet\b", value) or (os == "Android" and "Mobile" not in value):
        device_type = "tablet"
    elif re.search(r"\bMobile\b|\biPhone\b", value):
        device_type = "mobile"
    elif os in {"Windows", "macOS", "Linux", "ChromeOS"}:
        device_type = "desktop"
    else:
        device_type = "unknown"
    return Device(browser=browser, os=os, device_type=device_type)
