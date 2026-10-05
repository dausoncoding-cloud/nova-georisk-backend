from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_CSP = (
    "default-src 'self'; base-uri 'self'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob: https://*.tile.openstreetmap.org "
    "https://*.basemaps.cartocdn.com; connect-src 'self'; "
    "font-src 'self' data:; worker-src 'self' blob:; frame-src 'none'; "
    "frame-ancestors 'none'; object-src 'none'; form-action 'self'"
)


def _content_security_policy(path: Path) -> str:
    prefix = 'add_header Content-Security-Policy "'
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    matches = [line for line in lines if line.startswith(prefix)]
    assert len(matches) == 1, f"Expected one CSP header in {path}"
    return matches[0][len(prefix) :].removesuffix('" always;')


def test_gateway_and_production_browser_csp_are_identical_and_gis_safe():
    gateway = _content_security_policy(ROOT / "deploy/nginx/conf.d/gateway.conf")
    production = _content_security_policy(ROOT / "deploy/nginx/app.novageorisk.com.conf.example")

    assert gateway == production == EXPECTED_CSP
    assert "img-src 'self' data: blob: https://*.tile.openstreetmap.org" in gateway
    assert "https://*.basemaps.cartocdn.com" in gateway
    assert "script-src 'self'" in gateway
    assert "connect-src 'self'" in gateway
    assert "frame-src 'none'" in gateway
    assert "object-src 'none'" in gateway
    assert "script-src *" not in gateway
    assert "img-src *" not in gateway
