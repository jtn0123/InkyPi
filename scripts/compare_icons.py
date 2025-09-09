#!/usr/bin/env python3
"""
Side-by-side weather icon comparison utility.

Compares InkyPi's current OWM-style icon set (src/plugins/weather/icons)
against a candidate icon pack directory and generates an HTML matrix for
visual review (one row per icon code).

Usage:
  python scripts/compare_icons.py --new-dir /path/to/new/pack \
    --out mock_display_output/icon_compare.html

Optional mapping JSON:
  A JSON dict mapping OWM codes (e.g., "10n") to relative paths inside
  the new pack directory. Pass with --map path/to/map.json

This script does not modify the app; it produces a static HTML report.
"""

import argparse
import base64
import os
from typing import Dict, Optional


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CURRENT_DIR = os.path.join(REPO_ROOT, "src", "plugins", "weather", "icons")


OWM_CODES = [
    # Clear/Clouds/Rain/Thunder/Snow/Mist (day/night)
    "01d", "01n", "02d", "02n", "03d", "03n", "04d", "04n",
    "09d", "09n", "10d", "10n", "11d", "11n", "13d", "13n",
    "50d", "50n",
]

# Short descriptions for OWM icon families (see OWM docs)
# 01x clear, 02x few clouds, 03x scattered clouds, 04x broken/overcast,
# 09x shower rain/drizzle, 10x rain, 11x thunder, 13x snow, 50x mist/haze/fog.
OWM_DESCRIPTIONS = {
    "01": "Clear sky",
    "02": "Few clouds (11–25%)",
    "03": "Scattered clouds (25–50%)",
    "04": "Broken/overcast clouds (51–100%)",
    "09": "Shower rain / drizzle",
    "10": "Rain",
    "11": "Thunderstorm",
    "13": "Snow",
    "50": "Mist / Haze / Fog (Atmosphere)",
}

# Moon phase keys available in our app (PNG set)
MOON_PHASES = [
    ("newmoon", "New Moon"),
    ("firstquarter", "First Quarter"),
    ("fullmoon", "Full Moon"),
    ("lastquarter", "Last Quarter"),
    ("waxingcrescent", "Waxing Crescent"),
    ("waxinggibbous", "Waxing Gibbous"),
    ("waninggibbous", "Waning Gibbous"),
    ("waningcrescent", "Waning Crescent"),
]
# Group → suggested icon paths in the candidate pack (day/night), based on
# OpenWeather condition code families. These are best-effort visual matches
# to the Makin‑Things set.
PACK_SUGGESTIONS = {
    "2xx Thunderstorm": (
        "original/static/thunderstorms.svg",
        "original/static/isolated-thunderstorms-night.svg",
    ),
    "3xx Drizzle": (
        "original/static/rainy-1-day.svg",
        "original/static/rainy-1-night.svg",
    ),
    "5xx Rain": (
        "original/static/rainy-2-day.svg",
        "original/static/rainy-2-night.svg",
    ),
    "6xx Snow": (
        "original/static/snowy-2-day.svg",
        "original/static/snowy-2-night.svg",
    ),
    "7xx Atmosphere (mist/haze/fog/etc)": (
        "original/static/fog-day.svg",
        "original/static/fog-night.svg",
    ),
    "800 Clear": (
        "original/static/clear-day.svg",
        "original/static/clear-night.svg",
    ),
    "801 Few clouds": (
        "original/static/cloudy-1-day.svg",
        "original/static/cloudy-1-night.svg",
    ),
    "802 Scattered clouds": (
        "original/static/cloudy-2-day.svg",
        "original/static/cloudy-2-night.svg",
    ),
    "803–804 Broken/overcast": (
        "original/static/cloudy-3-day.svg",
        "original/static/cloudy-3-night.svg",
    ),
}


def to_data_uri(path: str) -> str:
    try:
        with open(path, "rb") as f:
            data = f.read()
        b64 = base64.b64encode(data).decode("ascii")
        ext = os.path.splitext(path)[1].lower()
        if ext == ".svg":
            mime = "image/svg+xml"
        elif ext in (".jpg", ".jpeg"):
            mime = "image/jpeg"
        elif ext == ".gif":
            mime = "image/gif"
        elif ext == ".webp":
            mime = "image/webp"
        else:
            mime = "image/png"
        return f"data:{mime};base64,{b64}"
    except Exception:
        return ""


def find_in_dir(root: str, filename: str) -> Optional[str]:
    candidate = os.path.join(root, filename)
    if os.path.exists(candidate):
        return candidate
    for dirpath, _dirnames, filenames in os.walk(root):
        if filename in filenames:
            return os.path.join(dirpath, filename)
    return None


def main():
    ap = argparse.ArgumentParser(description="Compare weather icons (OWM codes)")
    ap.add_argument("--new-dir", required=True, help="Path to candidate icon pack root")
    ap.add_argument("--out", default=os.path.join(REPO_ROOT, "mock_display_output", "icon_compare.html"))
    ap.add_argument("--map", help="Optional JSON mapping file: { '10n': 'path/in/new/dir.png', ... }")
    ap.add_argument("--new-dir2", help="Second candidate pack root to compare (optional)")
    ap.add_argument("--map2", help="Optional JSON mapping file for second pack")
    ap.add_argument("--new-dir3", help="Third candidate pack root to compare (optional)")
    ap.add_argument("--map3", help="Optional JSON mapping file for third pack")
    ap.add_argument("--repo-url", help="Public base URL for pack A (e.g., https://github.com/Makin-Things/weather-icons/blob/main/)")
    ap.add_argument("--repo-url2", help="Public base URL for pack B")
    ap.add_argument("--repo-url3", help="Public base URL for pack C")
    ap.add_argument("--citations-out", help="Optional JSON file to write per-icon citations")
    args = ap.parse_args()

    mapping: Dict[str, str] = {}
    if args.map and os.path.exists(args.map):
        import json
        with open(args.map, "r", encoding="utf-8") as f:
            mapping = json.load(f)
    mapping2: Dict[str, str] = {}
    if args.map2 and os.path.exists(args.map2):
        import json
        with open(args.map2, "r", encoding="utf-8") as f:
            mapping2 = json.load(f)
    mapping3: Dict[str, str] = {}
    if args.map3 and os.path.exists(args.map3):
        import json
        with open(args.map3, "r", encoding="utf-8") as f:
            mapping3 = json.load(f)

    rows = []
    missing = []
    found = 0

    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    def resolve_new(pack_root: str, mapping_dict: Dict[str, str], code: str) -> str:
        if not pack_root:
            return ""
        mapped = mapping_dict.get(code)
        if mapped:
            candidate = os.path.join(pack_root, mapped)
            if not os.path.exists(candidate) and "/original/" in candidate:
                candidate_alt = candidate.replace("/original/", "/", 1)
                candidate = candidate_alt if os.path.exists(candidate_alt) else candidate
            return candidate if os.path.exists(candidate) else ""
        np = find_in_dir(pack_root, f"{code}.png")
        return np or ""

    def relative_in_pack(pack_root: str, mapping_dict: Dict[str, str], code: str, resolved_path: str) -> str:
        mapped = mapping_dict.get(code)
        if mapped:
            return mapped
        if pack_root and resolved_path and resolved_path.startswith(pack_root):
            rel = os.path.relpath(resolved_path, pack_root)
            return rel.replace(os.sep, "/")
        return ""

    for code in OWM_CODES:
        current_path = os.path.join(CURRENT_DIR, f"{code}.png")
        current_uri = to_data_uri(current_path) if os.path.exists(current_path) else ""
        new_path = resolve_new(args.new_dir, mapping, code)
        new_path2 = resolve_new(args.new_dir2, mapping2, code)
        new_path3 = resolve_new(args.new_dir3, mapping3, code)
        new_uri = to_data_uri(new_path) if new_path else ""
        new_uri2 = to_data_uri(new_path2) if new_path2 else ""
        new_uri3 = to_data_uri(new_path3) if new_path3 else ""

        relA = relative_in_pack(args.new_dir, mapping, code, new_path)
        relB = relative_in_pack(args.new_dir2, mapping2, code, new_path2)
        relC = relative_in_pack(args.new_dir3, mapping3, code, new_path3)
        ghA = (args.repo_url.rstrip("/") + "/" + relA) if (args.repo_url and relA) else ""
        ghB = (args.repo_url2.rstrip("/") + "/" + relB) if (args.repo_url2 and relB) else ""
        ghC = (args.repo_url3.rstrip("/") + "/" + relC) if (args.repo_url3 and relC) else ""

        status = "OK" if new_uri else "MISSING"
        if status == "OK":
            found += 1
        else:
            missing.append(code)

        rows.append((code, current_uri, new_uri, new_uri2, new_uri3, status, current_path, new_path or "", new_path2 or "", new_path3 or "", ghA, ghB, ghC))

    # Build HTML
    html = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'>",
        "<title>Icon Compare</title>",
        "<style>body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Arial,sans-serif}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:8px;text-align:left;vertical-align:top}th{background:#f6f6f6}img.thumb-sm{width:48px;height:48px}img.thumb-lg{width:128px;height:128px}code{background:#f2f2f2;padding:2px 4px;border-radius:3px}</style>",
        "</head><body>",
        f"<h2>Weather Icon Comparison</h2>",
        f"<p>Current set: {CURRENT_DIR}</p>",
        f"<p>New set: {args.new_dir}</p>",
        f"<p>Found {found}/{len(OWM_CODES)} icons. Missing: {', '.join(missing) if missing else 'None'}</p>",
        "<p><strong>OpenWeather icon families</strong> (per their docs: <a href=\"https://openweathermap.org/weather-conditions\">openweathermap.org/weather-conditions</a>): 01x—Clear; 02x—Few clouds; 03x—Scattered clouds; 04x—Broken/overcast; 09x—Shower rain/drizzle; 10x—Rain; 11x—Thunderstorm; 13x—Snow; 50x—Mist/Haze/Fog. Day vs night variants use the trailing letter <code>d</code> or <code>n</code> respectively.</p>",
        "<table><thead><tr><th>Code</th><th>Current (48/128)</th><th>Pack A (48/128)</th><th>Pack B (48/128)</th><th>Pack C (48/128)</th><th>Status(A)</th><th>Current Path</th><th>Pack A Path</th><th>Pack B Path</th><th>Pack C Path</th><th>Pack A Link</th><th>Pack B Link</th><th>Pack C Link</th></tr></thead><tbody>",
    ]

    citations = []
    for code, cur, new, new2, new3, status, curp, newp, newp2, newp3, ghA, ghB, ghC in rows:
        html.append("<tr>")
        desc = OWM_DESCRIPTIONS.get(code[:2], "")
        html.append(f"<td>{code}<div style='color:#555;font-size:12px'>{desc}</div></td>")
        if cur:
            html.append(f"<td><a href='file://{curp}'><img class='thumb-sm' src='{cur}'></a><br><a href='file://{curp}'><img class='thumb-lg' src='{cur}'></a></td>")
        else:
            html.append("<td>—</td>")
        if new:
            html.append(f"<td><a href='file://{newp}'><img class='thumb-sm' src='{new}'></a><br><a href='file://{newp}'><img class='thumb-lg' src='{new}'></a></td>")
        else:
            html.append("<td>—</td>")
        if new2:
            html.append(f"<td><a href='file://{newp2}'><img class='thumb-sm' src='{new2}'></a><br><a href='file://{newp2}'><img class='thumb-lg' src='{new2}'></a></td>")
        else:
            html.append("<td>—</td>")
        if new3:
            html.append(f"<td><a href='file://{newp3}'><img class='thumb-sm' src='{new3}'></a><br><a href='file://{newp3}'><img class='thumb-lg' src='{new3}'></a></td>")
        else:
            html.append("<td>—</td>")
        html.append(f"<td>{status}</td>")
        html.append(f"<td style='font-size:12px;color:#555'>{curp}</td>")
        html.append(f"<td style='font-size:12px;color:#555'>{newp}</td>")
        html.append(f"<td style='font-size:12px;color:#555'>{newp2}</td>")
        html.append(f"<td style='font-size:12px;color:#555'>{newp3}</td>")
        html.append(f"<td>{('<a href=\'%s\' target=\'_blank\'>GitHub</a>' % ghA) if ghA else '—'}</td>")
        html.append(f"<td>{('<a href=\'%s\' target=\'_blank\'>GitHub</a>' % ghB) if ghB else '—'}</td>")
        html.append(f"<td>{('<a href=\'%s\' target=\'_blank\'>GitHub</a>' % ghC) if ghC else '—'}</td>")
        html.append("</tr>")

        citations.append({
            "code": code,
            "current_path": curp,
            "pack_a": {"path": newp, "repo_url": ghA},
            "pack_b": {"path": newp2, "repo_url": ghB},
            "pack_c": {"path": newp3, "repo_url": ghC}
        })

    # Extras and Moon sections
    html.append("</tbody></table>")
    html.append("<h3>Extra Phenomena</h3>")
    html.append("<table><thead><tr><th>Name</th><th>Pack A</th><th>Pack B</th><th>Pack C</th><th>Path A</th><th>Path B</th><th>Path C</th></tr></thead><tbody>")
    for key, label in [("tornado","Tornado"),("hurricane","Hurricane"),("tropical-storm","Tropical Storm"),("rain-and-snow-mix","Rain & Snow Mix"),("rain-and-sleet-mix","Rain & Sleet Mix"),("fog","Fog (generic)")]:
        p1 = resolve_new(args.new_dir, mapping, key)
        p2 = resolve_new(args.new_dir2, mapping2, key)
        p3 = resolve_new(args.new_dir3, mapping3, key)
        u1 = to_data_uri(p1) if p1 else ""
        u2 = to_data_uri(p2) if p2 else ""
        u3 = to_data_uri(p3) if p3 else ""
        html.append("<tr>")
        html.append(f"<td>{label} <div style='color:#555;font-size:12px'>{key}</div></td>")
        html.append(f"<td>{('<img class=\'thumb-sm\' src=\'%s\'><br><img class=\'thumb-lg\' src=\'%s\'>' % (u1,u1)) if u1 else '—'}</td>")
        html.append(f"<td>{('<img class=\'thumb-sm\' src=\'%s\'><br><img class=\'thumb-lg\' src=\'%s\'>' % (u2,u2)) if u2 else '—'}</td>")
        html.append(f"<td>{('<img class=\'thumb-sm\' src=\'%s\'><br><img class=\'thumb-lg\' src=\'%s\'>' % (u3,u3)) if u3 else '—'}</td>")
        html.append(f"<td style='font-size:12px;color:#555'>{p1}</td>")
        html.append(f"<td style='font-size:12px;color:#555'>{p2}</td>")
        html.append(f"<td style='font-size:12px;color:#555'>{p3}</td>")
        html.append("</tr>")
    html.append("</tbody></table>")

    html.append("<h3>Moon Phases</h3>")
    html.append("<table><thead><tr><th>Phase</th><th>Current (PNG)</th><th>Pack A</th><th>Pack B</th><th>Pack C</th><th>Path A</th><th>Path B</th><th>Path C</th></tr></thead><tbody>")
    for key, label in MOON_PHASES:
        curp2 = os.path.join(CURRENT_DIR, f"{key}.png")
        curu2 = to_data_uri(curp2) if os.path.exists(curp2) else ""
        p1m = resolve_new(args.new_dir, mapping, key)
        p2m = resolve_new(args.new_dir2, mapping2, key)
        p3m = resolve_new(args.new_dir3, mapping3, key)
        u1m = to_data_uri(p1m) if p1m else ""
        u2m = to_data_uri(p2m) if p2m else ""
        u3m = to_data_uri(p3m) if p3m else ""
        html.append("<tr>")
        html.append(f"<td>{label} <div style='color:#555;font-size:12px'>{key}</div></td>")
        html.append(f"<td>{('<img class=\'thumb-sm\' src=\'%s\'><br><img class=\'thumb-lg\' src=\'%s\'>' % (curu2,curu2)) if curu2 else '—'}</td>")
        html.append(f"<td>{('<img class=\'thumb-sm\' src=\'%s\'><br><img class=\'thumb-lg\' src=\'%s\'>' % (u1m,u1m)) if u1m else '—'}</td>")
        html.append(f"<td>{('<img class=\'thumb-sm\' src=\'%s\'><br><img class=\'thumb-lg\' src=\'%s\'>' % (u2m,u2m)) if u2m else '—'}</td>")
        html.append(f"<td>{('<img class=\'thumb-sm\' src=\'%s\'><br><img class=\'thumb-lg\' src=\'%s\'>' % (u3m,u3m)) if u3m else '—'}</td>")
        html.append(f"<td style='font-size:12px;color:#555'>{p1m}</td>")
        html.append(f"<td style='font-size:12px;color:#555'>{p2m}</td>")
        html.append(f"<td style='font-size:12px;color:#555'>{p3m}</td>")
        html.append("</tr>")
    html.extend(["</tbody></table>", "</body></html>"])

    if args.citations_out:
        import json
        with open(args.citations_out, "w", encoding="utf-8") as cf:
            json.dump(citations, cf, indent=2)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(html))

    print(f"Wrote: {args.out}")


if __name__ == "__main__":
    main()


