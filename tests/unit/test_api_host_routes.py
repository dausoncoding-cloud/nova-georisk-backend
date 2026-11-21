"""Security review M1: on the public API host (api.novageorisk.com), the NOVA ARI console, billing and per-user
session routes do not exist; they are served only through the gateway and BFF."""
import re
from pathlib import Path

APP_CONF = Path(__file__).resolve().parents[2] / "deploy" / "nginx" / "conf.d" / "app.conf"
DENY = "location ~* ^/api/v1/(platform-admin|billing|account)(/|$) {"


def _https_server() -> str:
    text = APP_CONF.read_text(encoding="utf-8")
    return text[text.index("listen 443 ssl;"):]


def test_api_host_refuses_console_billing_and_account_routes():
    server = _https_server()
    assert DENY in server, "deny block missing from the HTTPS server of app.conf"
    block = server[server.index(DENY):server.index("\n    }", server.index(DENY))]
    assert "return 404" in block
    # A regex location wins over the plain "location /" prefix unless a ^~ prefix shadows it.
    assert server.index(DENY) < server.index("\n    location / {")
    assert not re.search(r"location \^~ /api", server)


def test_deny_pattern_matches_exactly_the_three_route_families():
    pattern = re.compile(r"^/api/v1/(platform-admin|billing|account)(/|$)", re.I)
    for path in ("/api/v1/platform-admin/access", "/api/v1/billing", "/api/v1/billing/summary", "/api/v1/account/sessions",
                 "/API/v1/Billing/summary"):
        assert pattern.search(path), path
    for path in ("/api/v1/projects", "/api/v1/billingx", "/api/v1/accounts", "/health",
                 "/api/v1/organizations/x/administration/login-history"):
        assert not pattern.search(path), path
