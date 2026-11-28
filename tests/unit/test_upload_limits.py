"""Owner decision 2026-11-27: 50 MB on the External data upload route only, at the edge, the gateway and the app;
every other route keeps 20 MB. Security review M1/L8: the Abliner webhook location is the one place with a smaller
cap (64k), in both files; nothing else may set a body size."""
import re
from pathlib import Path

import pytest

from app.services import external_data
from app.services.source_data.validators import MAX_BYTES

ROOT = Path(__file__).resolve().parents[2] / "deploy" / "nginx"
CONFIGS = [ROOT / "production-edge" / "frontend-app.conf", ROOT / "conf.d" / "gateway.conf"]
UPLOAD = r"^/api/v1/projects/[0-9a-fA-F-]{36}/external-datasets$"
PID = "6f1c2e2a-0c4b-4b8e-9a5c-2f6a1d3e4b5c"
WEBHOOK_OPENING = "location = /api/v1/webhooks/abliner {"


def _body_limits(text: str) -> list[tuple[int, str]]:
    """(brace depth, value) for every client_max_body_size."""
    out, depth = [], 0
    for line in text.splitlines():
        code = line.split("#", 1)[0]
        match = re.search(r"client_max_body_size\s+(\S+);", code)
        if match:
            out.append((depth, match.group(1)))
        depth += code.count("{") - code.count("}")
    return out


def _block(text: str, opening: str) -> str:
    """The body of the block that starts with `opening` (its own braces only)."""
    start = text.index(opening) + len(opening)
    depth, end = 1, start
    while depth:  # the block's own braces (a regex's {36} is before the opening brace)
        depth += {"{": 1, "}": -1}.get(text[end], 0)
        end += 1
    return text[start:end]


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.name)
def test_only_the_upload_location_gets_50m_and_the_server_keeps_20m(path):
    text = path.read_text()
    limits = [(d, v) for d, v in _body_limits(text) if v != "64k"]  # the webhook cap: next test
    assert ("20m" in [v for _, v in limits]) and [v for _, v in limits].count("50m") == 1 and set(v for _, v in limits) == {"20m", "50m"}
    server_level = [d for d, v in limits if v == "20m"]
    upload_level = [d for d, v in limits if v == "50m"]
    assert max(server_level) < min(upload_level)  # 20m at server level; 50m only inside the nested upload location
    block = _block(text, f'location ~ "{UPLOAD}" {{')  # quoted: nginx needs quotes around a regex containing {}
    assert "client_max_body_size 50m;" in block and 'proxy_set_header X-Internal-Secret "";' in block
    assert 'proxy_set_header X-Nova-Role "";' in block and 'proxy_set_header X-Nova-Session-Ref "";' in block


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.name)
def test_64k_only_inside_the_abliner_webhook_location(path):
    text = path.read_text()
    assert [v for _, v in _body_limits(text)].count("64k") == 1
    block = _block(text, WEBHOOK_OPENING)
    assert "client_max_body_size 64k;" in block  # the one 64k is this block's
    assert "location" not in block  # exact match, nothing nested that could change the cap
    for header in ("Cookie", "Authorization", "X-Internal-Secret", "X-Nova-User-Id", "X-Nova-Organization-Id",
                   "X-Nova-Role", "X-Nova-Session-Ref"):
        assert f'proxy_set_header {header} "";' in block
    assert text.index(WEBHOOK_OPENING) < text.index("location ^~ /api/ {")  # declared at server level, before /api/


ZONES = {"frontend-app.conf": ROOT / "production-edge" / "app.conf", "gateway.conf": ROOT / "conf.d" / "gateway.conf"}
BROWSER_ZONES = {"nova_release_browser_api", "nova_release_browser_auth", "nova_gateway_api", "nova_gateway_auth"}


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.name)
def test_r4_5_the_abliner_webhook_location_is_post_only_with_its_own_rate_limit_zone(path):
    """Security review round 4, item 5: POST only, and a rate-limit zone of its own (never a browser zone), defined
    in the file that holds that server's zones (the edge's are in production-edge/app.conf, loaded with it)."""
    block = _block(path.read_text(), WEBHOOK_OPENING)
    code = "\n".join(line.split("#", 1)[0] for line in block.splitlines())
    post_only = (re.search(r"limit_except\s+POST\s*\{\s*deny\s+all;\s*\}", code)
                 or re.search(r"if \(\$request_method != POST\) \{\s*return 404", code))
    assert post_only, "the webhook location must refuse every method but POST"
    zones = re.findall(r"limit_req\s+zone=(\w+)", code)
    assert len(zones) == 1 and zones[0] not in BROWSER_ZONES, zones
    declared = re.findall(r"^limit_req_zone\s+\$binary_remote_addr\s+zone=(\w+):", ZONES[path.name].read_text(), re.M)
    assert zones[0] in declared


@pytest.mark.parametrize("url,matches", [
    (f"/api/v1/projects/{PID}/external-datasets", True),
    (f"/api/v1/projects/{PID}/external-datasets/", False),
    (f"/api/v1/projects/{PID}/external-datasets/x/review", False),
    (f"/api/v1/projects/{PID}/aois", False),
    ("/api/v1/source-datasets", False),
    ("/api/v1/analyses", False),
    (f"/api/v1/projects/{PID}/../{PID}/external-datasets", False),
    ("/api/v1/projects/not-a-project-id/external-datasets", False),
])
def test_the_upload_pattern_matches_only_the_upload_route(url, matches):
    assert bool(re.match(UPLOAD, url)) is matches


def test_the_app_limits():
    assert external_data.MAX_UPLOAD_BYTES == 50 * 1024 * 1024
    assert MAX_BYTES == 100 * 1024 * 1024  # the API-only source-datasets route is unchanged
