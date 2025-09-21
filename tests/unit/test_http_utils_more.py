import requests


def test_http_client_headers_and_ssl_verify(monkeypatch):
    import src.utils.http_utils as http_utils

    http_utils._reset_shared_session_for_tests()

    captured = {}

    def fake_get(self, url, **kwargs):
        captured["headers"] = kwargs.get("headers")
        captured["verify"] = kwargs.get("verify")

        class R:
            status_code = 200
            content = b""

            def json(self):
                return {}

        return R()

    monkeypatch.setattr(requests.Session, "get", fake_get, raising=True)

    http_utils.http_get("https://secure.example.com", headers={"X-Test": "1"})
    hdrs = captured.get("headers") or {}
    assert isinstance(hdrs, dict)
    assert str(hdrs.get("User-Agent", "")).startswith("InkyPi/")
    assert hdrs.get("X-Test") == "1"
    # By default requests uses verify=True; our wrapper should not disable it
    assert captured["verify"] is None

