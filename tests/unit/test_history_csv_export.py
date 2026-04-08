# pyright: reportMissingImports=false
"""Tests for GET /history/export.csv (JTN CSV export of refresh history)."""

import csv
import io
import json
import os

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_history_entry(history_dir: str, stem: str, meta: dict | None = None) -> None:
    """Create a dummy PNG and optional sidecar JSON in *history_dir*."""
    png_path = os.path.join(history_dir, f"{stem}.png")
    with open(png_path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")  # minimal PNG magic bytes

    if meta is not None:
        json_path = os.path.join(history_dir, f"{stem}.json")
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh)


def _parse_csv(body: str) -> tuple[list[str], list[list[str]]]:
    """Return (headers, rows) from a CSV string."""
    reader = csv.reader(io.StringIO(body))
    rows = list(reader)
    if not rows:
        return [], []
    return rows[0], rows[1:]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_export_csv_returns_200(client):
    """GET /history/export.csv should return HTTP 200."""
    resp = client.get("/history/export.csv")
    assert resp.status_code == 200


def test_export_csv_content_type(client):
    """Response Content-Type must be text/csv."""
    resp = client.get("/history/export.csv")
    assert resp.content_type.startswith("text/csv")


def test_export_csv_content_disposition(client):
    """Response must carry an attachment Content-Disposition with .csv filename."""
    resp = client.get("/history/export.csv")
    cd = resp.headers.get("Content-Disposition", "")
    assert "attachment" in cd
    assert ".csv" in cd


def test_export_csv_correct_headers(client):
    """CSV header row must exactly match the specified column names."""
    resp = client.get("/history/export.csv")
    body = resp.get_data(as_text=True)
    headers, _ = _parse_csv(body)
    assert headers == [
        "timestamp",
        "plugin_id",
        "instance_name",
        "status",
        "duration_ms",
        "error_message",
    ]


def test_export_csv_empty_history_headers_only(client, device_config_dev):
    """When history is empty the response must contain only the header row."""
    # history_dir exists but is empty (conftest creates it)
    resp = client.get("/history/export.csv")
    body = resp.get_data(as_text=True)
    headers, rows = _parse_csv(body)
    assert headers == [
        "timestamp",
        "plugin_id",
        "instance_name",
        "status",
        "duration_ms",
        "error_message",
    ]
    assert rows == []


def test_export_csv_one_entry_produces_one_row(client, device_config_dev):
    """Each history entry must produce exactly one data row."""
    history_dir = device_config_dev.history_image_dir
    _write_history_entry(
        history_dir,
        "display_20240101_120000",
        {
            "refresh_time": "2024-01-01T12:00:00+00:00",
            "plugin_id": "weather",
            "plugin_instance": "my-weather",
            "status": "green",
            "duration_ms": 1234,
            "error_message": "",
        },
    )

    resp = client.get("/history/export.csv")
    body = resp.get_data(as_text=True)
    _, rows = _parse_csv(body)
    assert len(rows) == 1


def test_export_csv_row_values_match_sidecar(client, device_config_dev):
    """Data rows must reflect the values stored in the sidecar JSON."""
    history_dir = device_config_dev.history_image_dir
    meta = {
        "refresh_time": "2024-03-15T08:30:00+00:00",
        "plugin_id": "clock",
        "plugin_instance": "bedroom-clock",
        "status": "green",
        "duration_ms": 500,
        "error_message": "",
    }
    _write_history_entry(history_dir, "display_20240315_083000", meta)

    resp = client.get("/history/export.csv")
    body = resp.get_data(as_text=True)
    _, rows = _parse_csv(body)
    assert len(rows) == 1
    row = rows[0]
    assert row[0] == "2024-03-15T08:30:00+00:00"
    assert row[1] == "clock"
    assert row[2] == "bedroom-clock"
    assert row[3] == "green"
    assert row[4] == "500"
    assert row[5] == ""


def test_export_csv_multiple_entries(client, device_config_dev):
    """Multiple history entries produce multiple rows (one per entry)."""
    history_dir = device_config_dev.history_image_dir
    for i, stem in enumerate(
        [
            "display_20240101_120000",
            "display_20240102_130000",
            "display_20240103_140000",
        ]
    ):
        _write_history_entry(
            history_dir,
            stem,
            {
                "refresh_time": f"2024-01-0{i + 1}T12:00:00+00:00",
                "plugin_id": f"plugin_{i}",
                "plugin_instance": f"instance_{i}",
            },
        )

    resp = client.get("/history/export.csv")
    body = resp.get_data(as_text=True)
    _, rows = _parse_csv(body)
    assert len(rows) == 3


def test_export_csv_missing_sidecar_uses_mtime(client, device_config_dev):
    """Entries without a sidecar JSON should still appear, using mtime for timestamp."""
    history_dir = device_config_dev.history_image_dir
    # Write only the PNG, no sidecar
    png_path = os.path.join(history_dir, "display_20240201_100000.png")
    with open(png_path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")

    resp = client.get("/history/export.csv")
    body = resp.get_data(as_text=True)
    _, rows = _parse_csv(body)
    assert len(rows) == 1
    # timestamp must be non-empty (derived from mtime)
    assert rows[0][0] != ""
    # Other fields default to empty string
    assert rows[0][1] == ""  # plugin_id
    assert rows[0][2] == ""  # instance_name


def test_export_csv_escaping_commas_in_error_message(client, device_config_dev):
    """error_message containing commas must be properly CSV-escaped."""
    history_dir = device_config_dev.history_image_dir
    tricky = "Connection refused, retry 1, retry 2"
    _write_history_entry(
        history_dir,
        "display_20240401_090000",
        {
            "refresh_time": "2024-04-01T09:00:00+00:00",
            "plugin_id": "rss",
            "plugin_instance": "news",
            "error_message": tricky,
        },
    )

    resp = client.get("/history/export.csv")
    body = resp.get_data(as_text=True)
    _, rows = _parse_csv(body)
    assert len(rows) == 1
    assert rows[0][5] == tricky


def test_export_csv_escaping_quotes_in_error_message(client, device_config_dev):
    """error_message containing double-quotes must be properly CSV-escaped."""
    history_dir = device_config_dev.history_image_dir
    tricky = 'API returned "bad request"'
    _write_history_entry(
        history_dir,
        "display_20240402_090000",
        {
            "refresh_time": "2024-04-02T09:00:00+00:00",
            "plugin_id": "weather",
            "plugin_instance": "home",
            "error_message": tricky,
        },
    )

    resp = client.get("/history/export.csv")
    body = resp.get_data(as_text=True)
    _, rows = _parse_csv(body)
    assert len(rows) == 1
    assert rows[0][5] == tricky


def test_export_csv_escaping_newlines_in_error_message(client, device_config_dev):
    """error_message containing newlines must be properly CSV-escaped."""
    history_dir = device_config_dev.history_image_dir
    tricky = "Line one\nLine two"
    _write_history_entry(
        history_dir,
        "display_20240403_090000",
        {
            "refresh_time": "2024-04-03T09:00:00+00:00",
            "plugin_id": "calendar",
            "plugin_instance": "work",
            "error_message": tricky,
        },
    )

    resp = client.get("/history/export.csv")
    body = resp.get_data(as_text=True)
    _, rows = _parse_csv(body)
    assert len(rows) == 1
    assert rows[0][5] == tricky


def test_history_page_has_export_csv_link(client):
    """The history page must contain a link to /history/export.csv."""
    resp = client.get("/history")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "/history/export.csv" in body
