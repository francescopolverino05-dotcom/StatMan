from fastapi.testclient import TestClient

from statman.api import app

client = TestClient(app)


def test_logo_and_icons_served():
    for path, ctype in [
        ("/static/assets/statman-logo.png", "image/png"),
        ("/static/assets/favicon-32.png", "image/png"),
        ("/static/assets/favicon-16.png", "image/png"),
        ("/static/assets/apple-touch-icon.png", "image/png"),
        ("/static/assets/icon-192.png", "image/png"),
        ("/static/assets/icon-512.png", "image/png"),
        ("/favicon.ico", "image/"),
    ]:
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["content-type"].startswith(ctype), path
