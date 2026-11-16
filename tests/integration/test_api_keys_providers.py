"""Verify the managed API Keys page renders every provider card.

The input ids are listed by hand so a renamed card (the page script and the
browser tests find cards by these ids) fails here.
"""

from flask.testing import FlaskClient

ALL_INPUT_IDS = [
    "openai-input",
    "openweather-input",
    "nasa-input",
    "unsplash-input",
    "github-input",
    "googleai-input",
    "immich-input",
]


def test_managed_api_keys_renders_all_providers(client: FlaskClient) -> None:
    resp = client.get("/settings/api-keys")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    assert f"{len(ALL_INPUT_IDS)} providers" in body

    for input_id in ALL_INPUT_IDS:
        assert f'id="{input_id}"' in body, f"Missing provider input: {input_id}"
