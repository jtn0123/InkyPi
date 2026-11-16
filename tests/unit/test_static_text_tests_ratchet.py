"""Ratchet: tests/static/ may not grow.

tests/static/ holds tests that grep JS and CSS source text rather than driving
the page, so they miss real behaviour. New front-end tests belong in a
Playwright test under tests/integration/. This test fails when the count goes
up, and when it goes down, so CEILING always matches the real count.
"""

from pathlib import Path

# Lower this when a test under tests/static/ is removed or ported to Playwright.
CEILING = 54

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


def _count_static_text_tests() -> int:
    return len(list(STATIC_DIR.glob("test_*.py")))


def test_static_text_test_count_matches_ceiling() -> None:
    count = _count_static_text_tests()
    assert count <= CEILING, (
        f"tests/static/ has {count} test_*.py files, over the ceiling of {CEILING}. "
        "Those tests grep source text instead of driving the page. Write a "
        "Playwright test in tests/integration/ instead."
    )
    assert count >= CEILING, (
        f"tests/static/ has {count} test_*.py files, under the ceiling of {CEILING}. "
        f"Lower CEILING in tests/unit/test_static_text_tests_ratchet.py to {count}."
    )
