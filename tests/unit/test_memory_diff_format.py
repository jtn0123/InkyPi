"""Tests for the PR memory-diff comment formatter."""

from scripts.format_memory_diff import format_comment


def test_format_comment_groups_allocator_noise_by_package():
    base = {
        "backend": "memray",
        "total_rss_bytes": 10 * 1024 * 1024,
        "module_count": 100,
        "allocator_sample_limit": 500,
        "allocators": [
            {
                "location": "/opt/python/lib/python3.12/site-packages/lark/tree.py:67",
                "bytes": 2 * 1024 * 1024,
            },
            {
                "location": "/opt/python/lib/python3.12/site-packages/lark/lexer.py:215",
                "bytes": 1 * 1024 * 1024,
            },
        ],
    }
    pr = {
        "backend": "memray",
        "total_rss_bytes": 11 * 1024 * 1024,
        "module_count": 100,
        "allocator_sample_limit": 500,
        "allocators": [
            {
                "location": "/opt/python/lib/python3.12/site-packages/lark/tree.py:67",
                "bytes": 4 * 1024 * 1024,
            },
            {
                "location": "/opt/python/lib/python3.12/site-packages/lark/lexer.py:215",
                "bytes": 2 * 1024 * 1024,
            },
        ],
    }

    comment = format_comment(base, pr)

    assert "### Largest grouped allocator deltas" in comment
    assert "| `lark` | 3.00 MB | 6.00 MB | +3.00 MB |" in comment
    assert "Source-location detail" in comment


def test_format_comment_does_not_invent_zero_for_sampled_shared_location():
    base = {
        "backend": "memray",
        "total_rss_bytes": 0,
        "module_count": 0,
        "allocator_sample_limit": 500,
        "allocators": [
            {
                "location": "/opt/python/lib/python3.12/site-packages/werkzeug/http.py:1",
                "bytes": 512 * 1024,
            }
        ],
    }
    pr = {
        "backend": "memray",
        "total_rss_bytes": 0,
        "module_count": 0,
        "allocator_sample_limit": 500,
        "allocators": [
            {
                "location": "/opt/python/lib/python3.12/site-packages/werkzeug/http.py:1",
                "bytes": 768 * 1024,
            }
        ],
    }

    comment = format_comment(base, pr)

    assert "| `werkzeug/http.py:1` | 512.0 KB | 768.0 KB | +256.0 KB |" in comment
    assert "| `werkzeug/http.py:1` | 0 B |" not in comment
    assert "| `werkzeug/http.py:1` | 512.0 KB | 0 B |" not in comment

