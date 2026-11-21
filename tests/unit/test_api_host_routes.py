"""Security review M1 (owner decision): the public API host api.novageorisk.com serves only GET /health.
Everything else returns 404; services reach the API over the internal Docker network.

Behaviour (checked in an nginx 1.27 container): GET/HEAD /health -> API with identity headers blanked;
POST /health, /health/, /HEALTH, /api/*, /docs, /openapi.json, /auth/*, /outputs/*, percent-encoded, double-slash,
dot-segment and upper-case variants -> 404. This test pins the configuration that produces it."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP_CONF = ROOT / "deploy" / "nginx" / "conf.d" / "app.conf"
IDENTITY_HEADERS = ("X-Internal-Secret", "X-Nova-User-Id", "X-Nova-Organization-Id", "X-Nova-Role", "X-Nova-Session-Ref")


def _https_server() -> str:
    text = APP_CONF.read_text(encoding="utf-8")
    return text[text.index("listen 443 ssl;"):]


def _location(server: str, header: str) -> str:
    start = server.index(header)
    return server[start:server.index("\n    }", start)]


def test_only_health_is_served_and_everything_else_is_404():
    server = _https_server()
    locations = re.findall(r"^    location ([^{]+)\{", server, re.M)
    served = [loc.strip() for loc in locations if not loc.strip().startswith("@")]
    assert served == ["= /health", "/"], served  # nothing else: no /api, /docs, /auth, regex or ^~ blocks
    catch_all = _location(server, "    location / {")
    assert "return 404" in catch_all and not re.search(r"proxy_pass\s+http", catch_all)
    assert len(re.findall(r"proxy_pass\s+http", server)) == 1  # only inside /health


def test_health_is_get_only_and_carries_no_identity():
    health = _location(_https_server(), "    location = /health {")
    assert re.search(r"if \(\$request_method !~ \^\(GET\|HEAD\)\$\) \{\s*return 404", health)
    assert "proxy_pass http://$api_upstream;" in health
    for header in IDENTITY_HEADERS:
        assert f'proxy_set_header {header} "";' in health, header
    assert "proxy_pass_request_body off;" in health


def test_plain_http_only_redirects_or_serves_the_certificate_challenge():
    text = APP_CONF.read_text(encoding="utf-8")
    http_server = text[:text.index("listen 443 ssl;")]
    assert "proxy_pass" not in http_server
    assert "return 301 https://$host$request_uri;" in http_server


def test_services_use_the_internal_network_not_the_public_host():
    from app.core.config import Settings

    assert Settings.model_fields["internal_api_base_url"].default == "http://api:8000"
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "INTERNAL_API_BASE_URL=http://api:8000" in example
    for path in [*ROOT.joinpath("app").rglob("*.py"), *ROOT.joinpath("scripts").rglob("*.py")]:
        assert "api.novageorisk.com" not in path.read_text(encoding="utf-8"), path
