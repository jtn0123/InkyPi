# pyright: reportMissingImports=false
from datetime import UTC, datetime, timedelta

from hypothesis import HealthCheck, given, settings, strategies as st

from model import Playlist, PlaylistManager, RefreshInfo


@given(
    latest_epoch=st.integers(min_value=0, max_value=2_000_000_000),
    elapsed_s=st.integers(min_value=0, max_value=86_400),
    interval_s=st.integers(min_value=0, max_value=86_400),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_should_refresh_matches_elapsed_time(latest_epoch, elapsed_s, interval_s):
    latest = datetime.fromtimestamp(latest_epoch, tz=UTC)
    current = latest + timedelta(seconds=elapsed_s)
    assert PlaylistManager.should_refresh(latest, interval_s, current) is (
        elapsed_s >= interval_s
    )


@given(
    plugin_ids=st.lists(
        st.text(
            alphabet=st.characters(
                min_codepoint=97,
                max_codepoint=122,
            ),
            min_size=1,
            max_size=8,
        ),
        min_size=1,
        max_size=5,
        unique=True,
    )
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_playlist_reorder_accepts_valid_permutations(plugin_ids):
    playlist = Playlist(
        "P",
        "00:00",
        "24:00",
        plugins=[
            {
                "plugin_id": plugin_id,
                "name": plugin_id.upper(),
                "plugin_settings": {},
                "refresh": {},
            }
            for plugin_id in plugin_ids
        ],
    )

    reordered = list(reversed(plugin_ids))
    ok = playlist.reorder_plugins(
        [{"plugin_id": plugin_id, "name": plugin_id.upper()} for plugin_id in reordered]
    )

    assert ok is True
    assert [plugin.plugin_id for plugin in playlist.plugins] == reordered


@given(
    request_ms=st.one_of(st.none(), st.integers(min_value=0, max_value=60_000)),
    display_ms=st.one_of(st.none(), st.integers(min_value=0, max_value=60_000)),
    generate_ms=st.one_of(st.none(), st.integers(min_value=0, max_value=60_000)),
    preprocess_ms=st.one_of(st.none(), st.integers(min_value=0, max_value=60_000)),
    used_cached=st.one_of(st.none(), st.booleans()),
)
@settings(max_examples=75, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_refresh_info_roundtrip_preserves_optional_metrics(
    request_ms,
    display_ms,
    generate_ms,
    preprocess_ms,
    used_cached,
):
    payload = {
        "refresh_type": "Manual Update",
        "plugin_id": "clock",
        "refresh_time": None,
        "image_hash": None,
        "request_ms": request_ms,
        "display_ms": display_ms,
        "generate_ms": generate_ms,
        "preprocess_ms": preprocess_ms,
        "used_cached": used_cached,
    }

    roundtripped = RefreshInfo.from_dict(payload).to_dict()

    assert roundtripped["refresh_type"] == "Manual Update"
    assert roundtripped["plugin_id"] == "clock"
    if request_ms is None:
        assert "request_ms" not in roundtripped
    else:
        assert roundtripped["request_ms"] == request_ms
    if display_ms is None:
        assert "display_ms" not in roundtripped
    else:
        assert roundtripped["display_ms"] == display_ms
    if generate_ms is None:
        assert "generate_ms" not in roundtripped
    else:
        assert roundtripped["generate_ms"] == generate_ms
    if preprocess_ms is None:
        assert "preprocess_ms" not in roundtripped
    else:
        assert roundtripped["preprocess_ms"] == preprocess_ms
    if used_cached is None:
        assert "used_cached" not in roundtripped
    else:
        assert roundtripped["used_cached"] == used_cached
