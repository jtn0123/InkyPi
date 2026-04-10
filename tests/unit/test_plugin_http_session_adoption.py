"""Smoke test: verify that plugins use the shared HTTP session pool.

Each plugin that makes HTTP requests should call get_http_session() rather than
creating a bare requests.Session() or using the module-level requests.get().
This test patches get_http_session and confirms the wpotd plugin calls it, which
exercises the adoption pattern required by docs/http_performance.md.
"""

from unittest.mock import MagicMock, patch


def _make_fake_session(image_bytes: bytes) -> MagicMock:
    """Build a MagicMock session whose .get() returns plausible Wikimedia responses."""
    session = MagicMock()

    def _get(url, params=None, headers=None, timeout=None, **_kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()

        if params and params.get("prop") == "images":
            resp.json.return_value = {
                "query": {"pages": [{"images": [{"title": "File:Example.png"}]}]}
            }
        elif params and params.get("prop") == "imageinfo":
            resp.json.return_value = {
                "query": {
                    "pages": {
                        "1": {"imageinfo": [{"url": "http://example.com/img.png"}]}
                    }
                }
            }
        else:
            # Image download
            resp.content = image_bytes
        return resp

    session.get.side_effect = _get
    return session


def test_wpotd_calls_get_http_session(device_config_dev):
    """wpotd.generate_image() must go through get_http_session(), not bare requests."""
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (10, 6), "white").save(buf, format="PNG")
    image_bytes = buf.getvalue()

    fake_session = _make_fake_session(image_bytes)

    with patch(
        "plugins.wpotd.wpotd.get_http_session", return_value=fake_session
    ) as mock_get_session:
        from plugins.wpotd.wpotd import Wpotd

        plugin = Wpotd({"id": "wpotd"})
        # generate_image raises if something goes wrong; success means the session was used
        try:
            plugin.generate_image({}, device_config_dev)
        except Exception:
            pass  # image processing may fail with tiny test image; that's fine

        # The important assertion: get_http_session was called at least once
        mock_get_session.assert_called()


def test_weather_api_calls_get_http_session():
    """weather_api fetch functions must go through get_http_session()."""
    fake_session = MagicMock()
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "current_weather": {"temperature": 20.0, "weathercode": 0, "windspeed": 5.0},
        "hourly": {"time": [], "temperature_2m": []},
        "daily": {"time": [], "temperature_2m_max": [], "temperature_2m_min": []},
    }
    fake_session.get.return_value = fake_resp

    with patch(
        "plugins.weather.weather_api.get_http_session", return_value=fake_session
    ) as mock_get_session:
        from plugins.weather.weather_api import get_open_meteo_data

        try:
            get_open_meteo_data(lat=51.5, long=-0.1, units="metric", forecast_days=3)
        except Exception:
            pass

        mock_get_session.assert_called()
