"""P5: `autopilot serve`, a read-only live status page built from plan.yaml + state.db on every request."""
import threading
import urllib.error
import urllib.request

import pytest

from autopilot.report import html_page, is_loopback, status_server
from test_autopilot import make_project, phases_basic


def get(srv, path="/"):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}{path}", timeout=10) as r:
            return r.status, r.read().decode("utf-8"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8"), dict(e.headers)


@pytest.fixture
def serve(tmp_path):
    started, root = [], make_project(tmp_path, phases_basic())

    def start(**kw):
        srv = status_server(root, "127.0.0.1", 0, **kw)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        started.append(srv)
        return srv
    yield start
    for s in started:
        s.shutdown()
        s.server_close()


def test_page_shows_the_report_and_refreshes(serve):
    srv = serve(refresh=7)
    code, body, headers = get(srv)
    assert code == 200 and "text/html" in headers["Content-Type"] and headers["Cache-Control"] == "no-store"
    assert "Autopilot report" in body and "| P01 | One |" in body and "http-equiv=refresh content=7" in body
    assert get(srv, "/state.db")[0] == 404 and get(srv, "/.agent/plan.yaml")[0] == 404  # only the page


def test_token_is_required_when_set(serve):
    srv = serve(token="s3cret-token")
    assert get(srv)[0] == 403 and get(srv, "/?token=wrong")[0] == 403 and get(srv, "/?token=%C3%A9")[0] == 403
    assert get(srv, "/?token=s3cret-token")[0] == 200


def test_dns_rebinding_is_refused_without_a_token(serve):
    import http.client
    srv = serve()
    for host, code in (("evil.example:8765", 403), ("localhost:8765", 200), ("[::1]:8765", 200)):
        c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
        c.request("GET", "/", headers={"Host": host})
        assert c.getresponse().status == code, host
        c.close()


def test_public_bind_without_token_is_refused(tmp_path):
    with pytest.raises(ValueError, match="AUTOPILOT_STATUS_TOKEN"):
        status_server(tmp_path, "0.0.0.0", 0)
    assert is_loopback("127.0.0.1") and is_loopback("::1") and is_loopback("localhost")
    assert not is_loopback("0.0.0.0") and not is_loopback("example.com")


def test_report_text_is_escaped():
    assert "<script>" not in html_page("<script>alert(1)</script>") and "&lt;script&gt;" in html_page("<script>")
