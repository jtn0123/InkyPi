from plugins.weather.weather import Weather


def test_current_pack_has_all_core_condition_icons():
    w = Weather({"id": "weather"})

    # Core OpenWeatherMap icon codes (day/night variants)
    base_codes = [
        "01", "02", "03", "04", "09", "10", "11", "13", "50",
    ]
    codes = [f"{c}{s}" for c in base_codes for s in ("d", "n")]

    for code in codes:
        path = w._resolve_cond_icon_path(code, "current")
        # Should resolve to a file path or a fallback day variant
        assert isinstance(path, str)
        assert path.endswith(".png") and len(path) > 0


def test_current_pack_has_all_core_moon_phase_icons():
    w = Weather({"id": "weather"})

    phases = [
        "newmoon",
        "firstquarter",
        "fullmoon",
        "lastquarter",
        "waxingcrescent",
        "waxinggibbous",
        "waningcrescent",
        "waninggibbous",
    ]

    for phase in phases:
        path = w._resolve_moon_icon_path(phase, "current")
        assert isinstance(path, str)
        assert path.endswith(".png") and len(path) > 0



