"""Static checks for theme.js presence and key behavior hooks."""


def test_theme_script_exists(client):
    resp = client.get("/static/scripts/theme.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)

    # Basic behaviors present
    assert "localStorage.getItem('theme')" in js
    assert "document.documentElement.setAttribute('data-theme'" in js
    assert "getPreferredTheme()" in js
    assert "applyTheme(theme)" in js
    assert "themeToggle" in js

