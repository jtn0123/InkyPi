"""Tests for dashboard renderMeta title index tracking.

JTN-248: renderMeta hardcoded the title at row index 1, which caused the wrong
row to be italicised when no date/label row was present (title was at index 0
but caption at index 1 received the <em> treatment instead).
"""


def test_dashboard_page_script_exists(client):
    resp = client.get("/static/scripts/dashboard_page.js")
    assert resp.status_code == 200


def test_rendermeta_tracks_title_index_dynamically(client):
    """JTN-248: title italics must use a tracked index, not the hardcoded value 1.

    The buggy code used ``index === 1 && meta.title``.  The fix introduces a
    ``titleIndex`` variable that is set to the row's actual position when the
    title is pushed, then compared via ``index === titleIndex``.
    """
    resp = client.get("/static/scripts/dashboard_page.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # The fix must declare and initialise the tracking variable
    assert "let titleIndex = -1;" in js

    # Title push must record its position before pushing
    assert "titleIndex = rows.length;" in js

    # Render loop must use the dynamic index, not the hardcoded literal
    assert "index === titleIndex" in js

    # The old hardcoded guard must not exist anywhere in the file
    assert "index === 1 && meta.title" not in js
