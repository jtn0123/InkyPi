"""Verify the managed API Keys page renders all 6 provider cards."""

ALL_INPUT_IDS = [
    "openai-input",
    "openweather-input",
    "nasa-input",
    "unsplash-input",
    "github-input",
    "googleai-input",
]


def test_managed_api_keys_renders_all_six_providers(client):
    resp = client.get("/settings/api-keys")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    assert "6 providers" in body

    for input_id in ALL_INPUT_IDS:
        assert f'id="{input_id}"' in body, f"Missing provider input: {input_id}"
