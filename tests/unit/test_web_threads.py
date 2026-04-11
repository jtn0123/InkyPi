"""Tests for _get_web_threads() in src/inkypi.py (JTN-603)."""


class TestGetWebThreads:
    """Unit tests for _get_web_threads()."""

    def _get(self):
        """Import and return the _get_web_threads function."""
        import inkypi

        return inkypi._get_web_threads

    def test_default_web_threads_is_2(self, monkeypatch):
        """Unset env var returns the default of 2."""
        monkeypatch.delenv("INKYPI_WEB_THREADS", raising=False)
        fn = self._get()
        assert fn() == 2

    def test_env_override_to_4(self, monkeypatch):
        """INKYPI_WEB_THREADS=4 returns 4."""
        monkeypatch.setenv("INKYPI_WEB_THREADS", "4")
        fn = self._get()
        assert fn() == 4

    def test_env_override_to_8(self, monkeypatch):
        """INKYPI_WEB_THREADS=8 returns 8."""
        monkeypatch.setenv("INKYPI_WEB_THREADS", "8")
        fn = self._get()
        assert fn() == 8

    def test_invalid_env_falls_back_to_default(self, monkeypatch):
        """Non-numeric value falls back to default (2) without crashing."""
        monkeypatch.setenv("INKYPI_WEB_THREADS", "banana")
        fn = self._get()
        assert fn() == 2

    def test_empty_env_uses_default(self, monkeypatch):
        """Empty string falls back to default (2)."""
        monkeypatch.setenv("INKYPI_WEB_THREADS", "")
        fn = self._get()
        assert fn() == 2

    def test_zero_or_negative_clamped_to_1(self, monkeypatch):
        """Zero is clamped to 1 via max(1, value)."""
        monkeypatch.setenv("INKYPI_WEB_THREADS", "0")
        fn = self._get()
        assert fn() == 1

    def test_negative_clamped_to_1(self, monkeypatch):
        """Negative value is clamped to 1 via max(1, value)."""
        monkeypatch.setenv("INKYPI_WEB_THREADS", "-5")
        fn = self._get()
        assert fn() == 1
