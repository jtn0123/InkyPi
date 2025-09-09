#!/usr/bin/env python3
"""
Render the Weather plugin on-demand with mocked API responses (no real tokens).

Usage examples (run from repo root):
  python scripts/render_weather_mock.py --layout ny_color --units imperial
  python scripts/render_weather_mock.py --out src/static/images/current_image_variant.png

This script monkeypatches network calls used by the Weather plugin so nothing
is fetched from the internet. It saves the rendered PNG to --out.
"""

import argparse
import os
import sys
from datetime import datetime, timezone, timedelta
import pytz


# Ensure src/ is on the import path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


def _build_fake_owm_payload(now: datetime, tz_str: str) -> dict:
    """Return a minimal One Call style payload with alerts, current, daily, hourly.

    Matches the fields our parser uses in plugins.weather.weather.
    """
    base_ts = int(now.replace(minute=0, second=0, microsecond=0, tzinfo=timezone.utc).timestamp())

    # 24 hours of hourly data starting from 'now'
    hourly = []
    for i in range(24):
        ts = base_ts + i * 3600
        # Diurnal temp curve (warmer late afternoon, cooler early AM)
        temp = 65 + 15 * __import__('math').sin((i - 4) * __import__('math').pi / 12)
        # POP cycles with fronts
        pop = max(0.0, min(1.0, 0.2 + 0.6 * (1 if 15 <= i <= 20 else (0.5 if 9 <= i <= 12 else 0))))
        # Rain bursts in evening hours
        rain_mm = 0.0
        if 16 <= i <= 18:
            rain_mm = 0.8 + 0.4 * (i - 16)
        elif 19 <= i <= 20:
            rain_mm = 1.2 - 0.6 * (i - 19)
        hourly.append({
            "dt": ts,
            "temp": round(temp, 1),
            "pop": pop,
            "rain": {"1h": rain_mm},
        })

    # 8 days of daily forecasts with moon phase (+sunrise/sunset for fallback)
    daily = []
    highs = [81, 74, 72, 72, 73, 71, 70, 69]
    lows = [65, 67, 66, 66, 65, 64, 64, 63]
    for i in range(8):
        ts = base_ts + i * 86400
        phase = (i * 0.12) % 1.0
        # Simple sunrise/sunset offsets for demo purposes
        sunrise = ts + 6 * 3600
        sunset = ts + 20 * 3600
        daily.append({
            "dt": ts,
            "weather": [{"icon": "01d" if i % 3 != 1 else "10d"}],
            "temp": {"max": highs[i], "min": lows[i]},
            "moon_phase": phase,
            "sunrise": sunrise,
            "sunset": sunset,
        })

    try:
        local_hour = now.astimezone(pytz.timezone(tz_str)).hour
    except Exception:
        local_hour = now.hour
    is_night_local = local_hour < 6 or local_hour >= 20

    return {
        "timezone": tz_str,
        "alerts": [
            {"event": "Heat Advisory"},
            {"event": "Air Quality Alert"},
        ],
        "current": {
            "dt": base_ts,
            "temp": 72,
            "feels_like": 72,
            # Alternate icons, switched to night set when local night
            "weather": [{"icon": ("01n" if is_night_local else "01d") if (now.hour % 3 == 0) else (("10n" if is_night_local else "10d") if (now.hour % 3 == 1) else ("03n" if is_night_local else "03d"))}],
            "clouds": 62,
            "humidity": 70,
            "pressure": 1016,
            "uvi": 0,
            "visibility": 12000,
            "wind_speed": 4.6,
            "wind_gust": 11.2,
            # Leave sunrise/sunset absent here to validate fallback path
        },
        "daily": daily,
        "hourly": hourly,
    }


def _make_fake_http_get(now: datetime, tz_str: str = "America/Los_Angeles"):
    """Return a function that mimics utils.http_get returning minimal objects."""

    fake_weather = _build_fake_owm_payload(now, tz_str)

    class _Resp:
        def __init__(self, payload):
            self.status_code = 200
            self._payload = payload
            # Minimal attributes used elsewhere
            self.content = b""

        def json(self):
            return self._payload

    def http_get(url, *args, **kwargs):  # signature-compatible
        if "air_pollution" in url:
            return _Resp({"list": [{"main": {"aqi": 2}}]})
        if "/geo/1.0/reverse" in url:
            return _Resp([
                {"name": "San Diego", "state": "CA", "country": "US"}
            ])
        # One-Call
        return _Resp(fake_weather)

    return http_get


def main():
    parser = argparse.ArgumentParser(description="Render weather with mocked APIs")
    parser.add_argument("--layout", default="ny_color", choices=["classic", "ny_color"], help="Layout style to render")
    parser.add_argument("--units", default="imperial", choices=["metric", "imperial", "standard"], help="Units for temperature/speed")
    parser.add_argument("--provider", default="OpenMeteo", choices=["OpenWeatherMap", "OpenMeteo"], help="Weather provider")
    parser.add_argument("--weather-pack", default="current", choices=["current","A","B","C"], help="Weather icon pack")
    parser.add_argument("--moon-pack", default="current", choices=["current","C"], help="Moon icon pack")
    parser.add_argument("--save-json", help="Save provider JSONs here (no refetch next time)")
    parser.add_argument("--use-json", help="Load provider JSONs from here instead of fetching")
    parser.add_argument("--variant", choices=["C5"], help="Visual variant set (C5 only)")
    parser.add_argument("--out", default=os.path.join("src", "static", "images", "current_image_variant.png"), help="Output PNG path")
    parser.add_argument("--width", type=int, default=800, help="Canvas width")
    parser.add_argument("--height", type=int, default=480, help="Canvas height")
    parser.add_argument("--composite", action="store_true", help="Generate composite preview with multiple variants")
    parser.add_argument("--night", action="store_true", help="Force night-time current icon for preview")
    parser.add_argument("--hour", type=int, help="Force hour for rendering (0-23)")
    parser.add_argument("--tz", default="America/Los_Angeles", help="Timezone name, e.g., Europe/London")
    parser.add_argument("--lat", type=float, default=32.7157, help="Latitude")
    parser.add_argument("--lon", type=float, default=-117.1611, help="Longitude")
    args = parser.parse_args()

    # Late imports after sys.path tweak
    from plugins.weather.weather import Weather

    # Monkeypatch network calls used by the weather plugin
    import plugins.weather.weather as weather_mod
    now = datetime.now(timezone.utc)
    if args.hour is not None:
        now = now.replace(hour=args.hour, minute=0, second=0, microsecond=0)
    if args.use_json:
        # Monkeypatch http_get to read JSON responses from local files
        import json as _json
        import plugins.weather.weather as weather_mod
        def _load_json(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return _json.load(f)
            except Exception:
                return None
        class _Resp:
            def __init__(self, payload):
                self.status_code = 200
                self._payload = payload
                self.content = b""
            def json(self):
                return self._payload
        def _json_http_get(url, *a, **kw):
            if "onecall" in url:
                p = _load_json(os.path.join(args.use_json, "weather.json"))
                return _Resp(p if p is not None else {})
            if "air_pollution" in url:
                p = _load_json(os.path.join(args.use_json, "aqi.json"))
                return _Resp(p if p is not None else {"list": [{"main": {"aqi": 2}}]})
            if "open-meteo.com" in url and "/forecast" in url:
                p = _load_json(os.path.join(args.use_json, "open_meteo_weather.json"))
                return _Resp(p if p is not None else {})
            if "air-quality-api.open-meteo" in url:
                p = _load_json(os.path.join(args.use_json, "open_meteo_aqi.json"))
                return _Resp(p if p is not None else {})
            if "/geo/1.0/reverse" in url:
                return _Resp([{"name": "Cached City", "state": "CA", "country": "US"}])
            return _Resp({})
        weather_mod.http_get = _json_http_get
    elif args.provider == "OpenMeteo":
        # For Open-Meteo, allow real network (no API key required) unless night override is requested
        if args.night:
            weather_mod.http_get = _make_fake_http_get(now, args.tz)
    else:
        # For OWM, stay mocked unless user provides a real key via env (not supported here)
        weather_mod.http_get = _make_fake_http_get(now, args.tz)

    # Minimal device config stub used by Weather.generate_image
    class _DevCfg:
        def __init__(self, width: int, height: int):
            self._res = (width, height)

        def get_resolution(self):
            return self._res

        def get_config(self, key, default=None):
            mapping = {
                "timezone": args.tz,
                "time_format": "12h",
                "orientation": "horizontal",
                "image_settings": {},
            }
            return mapping.get(key, default)

        def load_env_key(self, key: str):
            # Prevent real token usage
            return "fake"

    dev = _DevCfg(args.width, args.height)

    if args.composite:
        # Generate composite preview with 3/5/7 day variants
        from PIL import Image
        variants = []
        for days in [3, 5, 7]:
            p = Weather({"id": "weather"})
            settings = {
                "latitude": args.lat,
                "longitude": args.lon,
                "units": args.units,
                "weatherProvider": args.provider,
                "titleSelection": "location",
                "customTitle": ("London, United Kingdom" if abs(args.lat-51.5074)<1 and abs(args.lon-(-0.1278))<1 else "Custom Location"),
                "displayRefreshTime": "true",
                "displayMetrics": "true",
                "displayGraph": "true",
                "displayRain": "true",
                "displayForecast": "true",
                "forecastDays": days,
                "moonPhase": "true",
                "layoutStyle": args.layout,
            }
            if args.variant:
                settings[f"variant_{args.variant}"] = "true"
                
            img = p.generate_image(settings, dev)
            variants.append((img, f"{days}-day"))
        
        # Create composite image
        composite_width = sum(img.width for img, _ in variants)
        composite_height = max(img.height for img, _ in variants) + 30  # space for labels
        composite = Image.new("RGB", (composite_width, composite_height), "white")
        
        x_offset = 0
        from PIL import ImageDraw, ImageFont
        from typing import Union
        draw = ImageDraw.Draw(composite)
        
        font: Union[ImageFont.FreeTypeFont, ImageFont.ImageFont]
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", 20)
        except Exception:
            font = ImageFont.load_default()
            
        for img, label in variants:
            composite.paste(img, (x_offset, 30))
            # Draw label
            bbox = draw.textbbox((0, 0), label, font=font)
            text_width = bbox[2] - bbox[0]
            draw.text((x_offset + (img.width - text_width) // 2, 5), label, fill="black", font=font)
            x_offset += img.width
            
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        composite.save(args.out)
        print(f"Saved composite: {args.out}")
    else:
        # Single render
        p = Weather({"id": "weather"})
        settings = {
            "latitude": args.lat,
            "longitude": args.lon,
            "units": args.units,
            "weatherProvider": args.provider,
            "titleSelection": "location",
            "customTitle": ("London, United Kingdom" if abs(args.lat-51.5074)<1 and abs(args.lon-(-0.1278))<1 else "Custom Location"),
            "displayRefreshTime": "true",
            "displayMetrics": "true",
            "displayGraph": "true",
            "displayRain": "true",
            "displayForecast": "true",
            "forecastDays": 5,
            "moonPhase": "true",
            "layoutStyle": args.layout,
            "weatherIconPack": args.weather_pack,
            "moonIconPack": args.moon_pack,
        }
        if args.variant:
            settings[f"variant_{args.variant}"] = "true"
        if args.night:
            # Wrap the existing fake http_get (already set to our mock) and post-edit payload
            import plugins.weather.weather as weather_mod
            original_http_get = weather_mod.http_get
            def _night_http_get(url, *a, **kw):
                resp = original_http_get(url, *a, **kw)
                try:
                    payload = resp.json()
                    if isinstance(payload, dict) and "current" in payload:
                        try:
                            icon = payload["current"]["weather"][0]["icon"]
                            payload["current"]["weather"][0]["icon"] = icon.replace("d", "n")
                        except Exception:
                            pass
                    class _R:
                        def __init__(self, p):
                            self.status_code = 200
                            self._p = p
                            self.content = b""
                        def json(self):
                            return self._p
                    return _R(payload)
                except Exception:
                    return resp
            weather_mod.http_get = _night_http_get

        img = p.generate_image(settings, dev)
        if args.save_json and not args.use_json:
            # Save last fetched payloads if provider methods exist
            try:
                import json as _json
                os.makedirs(args.save_json, exist_ok=True)
                if args.provider == "OpenWeatherMap":
                    weather = p.get_weather_data("fake", args.units, args.lat, args.lon)
                    aqi = p.get_air_quality("fake", args.lat, args.lon)
                    with open(os.path.join(args.save_json, "weather.json"), "w", encoding="utf-8") as f:
                        _json.dump(weather, f)
                    with open(os.path.join(args.save_json, "aqi.json"), "w", encoding="utf-8") as f:
                        _json.dump(aqi, f)
                else:
                    w = p.get_open_meteo_data(args.lat, args.lon, args.units, 8)
                    a = p.get_open_meteo_air_quality(args.lat, args.lon)
                    with open(os.path.join(args.save_json, "open_meteo_weather.json"), "w", encoding="utf-8") as f:
                        _json.dump(w, f)
                    with open(os.path.join(args.save_json, "open_meteo_aqi.json"), "w", encoding="utf-8") as f:
                        _json.dump(a, f)
            except Exception:
                pass
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        img.save(args.out)
        print(f"Saved: {args.out}")


if __name__ == "__main__":
    main()


