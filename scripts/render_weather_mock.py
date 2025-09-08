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


# Ensure src/ is on the import path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


def _build_fake_owm_payload(now: datetime) -> dict:
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

    return {
        "timezone": "America/Los_Angeles",
        "alerts": [
            {"event": "Heat Advisory"},
            {"event": "Air Quality Alert"},
        ],
        "current": {
            "dt": base_ts,
            "temp": 72,
            "feels_like": 72,
            "weather": [{"icon": "01d"}],
            "humidity": 70,
            "pressure": 1016,
            "uvi": 0,
            "visibility": 12000,
            "wind_speed": 4.6,
            # Leave sunrise/sunset absent here to validate fallback path
        },
        "daily": daily,
        "hourly": hourly,
    }


def _make_fake_http_get(now: datetime):
    """Return a function that mimics utils.http_get returning minimal objects."""

    fake_weather = _build_fake_owm_payload(now)

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
    parser.add_argument("--variant", choices=["A", "B"], help="Visual variant for A/B testing")
    parser.add_argument("--out", default=os.path.join("src", "static", "images", "current_image_variant.png"), help="Output PNG path")
    parser.add_argument("--width", type=int, default=800, help="Canvas width")
    parser.add_argument("--height", type=int, default=480, help="Canvas height")
    parser.add_argument("--composite", action="store_true", help="Generate composite preview with multiple variants")
    args = parser.parse_args()

    # Late imports after sys.path tweak
    from plugins.weather.weather import Weather

    # Monkeypatch network calls used by the weather plugin
    import plugins.weather.weather as weather_mod
    now = datetime.now(timezone.utc)
    weather_mod.http_get = _make_fake_http_get(now)

    # Minimal device config stub used by Weather.generate_image
    class _DevCfg:
        def __init__(self, width: int, height: int):
            self._res = (width, height)

        def get_resolution(self):
            return self._res

        def get_config(self, key, default=None):
            mapping = {
                "timezone": "America/Los_Angeles",
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
                "latitude": 32.7157,
                "longitude": -117.1611,
                "units": args.units,
                "weatherProvider": "OpenWeatherMap",
                "titleSelection": "location",
                "customTitle": "San Diego, California",
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
        draw = ImageDraw.Draw(composite)
        
        try:
            from PIL.ImageFont import FreeTypeFont
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
            "latitude": 32.7157,
            "longitude": -117.1611,
            "units": args.units,
            "weatherProvider": "OpenWeatherMap",
            "titleSelection": "location",
            "customTitle": "San Diego, California",
            "displayRefreshTime": "true",
            "displayMetrics": "true",
            "displayGraph": "true",
            "displayRain": "true",
            "displayForecast": "true",
            "forecastDays": 5,
            "moonPhase": "true",
            "layoutStyle": args.layout,
        }
        if args.variant:
            settings[f"variant_{args.variant}"] = "true"

        img = p.generate_image(settings, dev)
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        img.save(args.out)
        print(f"Saved: {args.out}")


if __name__ == "__main__":
    main()


