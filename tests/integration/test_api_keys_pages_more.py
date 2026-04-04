def test_generic_api_keys_page_uses_canonical_template(client):
    resp = client.get("/api-keys")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert 'id="themeToggle"' in html
    assert "API Keys" in html
    assert "Add API Key" in html


def test_generic_api_keys_list_delete_button_has_aria_label(
    client, monkeypatch, tmp_path
):
    """JTN-202: list-view delete buttons include the key name in aria-label."""
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    env_file = tmp_path / ".env"
    env_file.write_text("MY_TEST_KEY=somevalue\n")

    resp = client.get("/api-keys")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert 'aria-label="Delete MY_TEST_KEY API key"' in html


def test_generic_api_keys_list_inputs_have_aria_labels(client, monkeypatch, tmp_path):
    """JTN-202: list-view key/value inputs include the key name in aria-label."""
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    env_file = tmp_path / ".env"
    env_file.write_text("ANOTHER_KEY=secretvalue\n")

    resp = client.get("/api-keys")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert 'aria-label="ANOTHER_KEY key name"' in html
    assert 'aria-label="ANOTHER_KEY value"' in html


def test_managed_api_keys_card_delete_button_has_aria_label(client, device_config_dev):
    """JTN-202: card-view delete button includes provider label in aria-label."""
    device_config_dev.set_env_key("NASA_SECRET", "nasa-test-value")

    resp = client.get("/settings/api-keys")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert 'aria-label="Delete NASA APOD key"' in html
