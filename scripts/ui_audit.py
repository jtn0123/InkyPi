#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

TOP_LEVEL_ROUTES = [
    ("home", "/"),
    ("settings", "/settings"),
    ("history", "/history"),
    ("playlist", "/playlist"),
    ("api_keys", "/settings/api-keys"),
]

VIEWPORTS = {
    "desktop_light": {
        "width": 1440,
        "height": 1200,
        "scheme": "light",
        "mobile": False,
    },
    "desktop_dark": {"width": 1440, "height": 1200, "scheme": "dark", "mobile": False},
    "mobile_light": {"width": 430, "height": 932, "scheme": "light", "mobile": True},
    "mobile_dark": {"width": 430, "height": 932, "scheme": "dark", "mobile": True},
}


@dataclass
class Scenario:
    name: str
    path: str


def discover_plugin_ids(repo_root: Path) -> list[str]:
    plugin_root = repo_root / "src" / "plugins"
    return sorted(
        path.name
        for path in plugin_root.iterdir()
        if path.is_dir()
        and path.name != "base_plugin"
        and not path.name.startswith("_")
        and (path / f"{path.name}.py").exists()
    )


def fill_form_and_extract(page):
    return page.evaluate(
        """
        () => {
          const form = document.querySelector('#settingsForm, #pluginForm');
          if (!form) return null;
          const today = new Date().toISOString().slice(0, 10);
          for (const element of Array.from(form.elements)) {
            if (!element.name || element.disabled) continue;
            if (element.type === 'hidden' || element.type === 'file') continue;
            if ((element.tagName === 'INPUT' || element.tagName === 'TEXTAREA') && !element.value) {
              if (element.type === 'date') element.value = today;
              else if (element.type === 'number') element.value = element.min || '1';
              else if (element.type === 'color') element.value = '#ffffff';
              else if (element.list) {
                const option = document.querySelector(`#${element.list.id} option`);
                if (option) element.value = option.value;
              } else if (element.required) {
                element.value = element.placeholder || `${element.name} sample`;
              }
              element.dispatchEvent(new Event('change', { bubbles: true }));
              element.dispatchEvent(new Event('input', { bubbles: true }));
            }
            if (element.tagName === 'SELECT' && !element.value && element.options.length) {
              const preferred = Array.from(element.options).find((opt) => opt.value !== '');
              element.value = preferred ? preferred.value : element.options[0].value;
              element.dispatchEvent(new Event('change', { bubbles: true }));
            }
          }
          const data = {};
          const fd = new FormData(form);
          for (const [key, value] of fd.entries()) {
            if (!(key in data)) data[key] = value;
          }
          return data;
        }
        """
    )


def stub_external_assets(page):
    page.route(
        "**://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
        lambda route: route.fulfill(status=200, content_type="text/css", body=""),
    )
    page.route(
        "**://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
        lambda route: route.fulfill(
            status=200,
            content_type="application/javascript",
            body="""
              (() => {
                function chain() { return this; }
                function markerFactory() {
                  return {
                    addTo: chain,
                    bindPopup: chain,
                    openPopup: chain,
                    setLatLng: chain,
                  };
                }
                window.L = {
                  map() {
                    return {
                      setView: chain,
                      on: chain,
                      off: chain,
                      fitBounds: chain,
                      addLayer: chain,
                      removeLayer: chain,
                      invalidateSize: chain,
                      closePopup: chain,
                    };
                  },
                  tileLayer() {
                    return { addTo: chain };
                  },
                  marker: markerFactory,
                  latLng(lat, lng) {
                    return { lat, lng };
                  },
                };
              })();
            """,
        ),
    )


def create_plugin_scenarios(base_url: str, plugin_id: str) -> list[Scenario]:
    scenarios = [Scenario("default", f"/plugin/{plugin_id}")]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        stub_external_assets(page)
        page.goto(
            f"{base_url}/plugin/{plugin_id}",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        page.wait_for_timeout(600)
        payload = fill_form_and_extract(page)
        browser.close()
    if not payload:
        return scenarios

    session = requests.Session()
    payload["plugin_id"] = plugin_id
    try:
        session.post(f"{base_url}/save_plugin_settings", data=payload, timeout=20)
        scenarios.append(Scenario("saved", f"/plugin/{plugin_id}"))
    except Exception:
        return scenarios

    try:
        instance_name = f"Audit {plugin_id}"
        add_payload = dict(payload)
        add_payload["refresh_settings"] = json.dumps(
            {
                "playlist": "Default",
                "instance_name": instance_name,
                "refreshType": "interval",
                "interval": "60",
                "unit": "minute",
            }
        )
        session.post(f"{base_url}/add_plugin", data=add_payload, timeout=20)
        scenarios.append(
            Scenario(
                "instance",
                f"/plugin/{plugin_id}?{urlencode({'instance': instance_name})}",
            )
        )
    except Exception:
        pass

    return scenarios


def collect_dom_issues(page, route_name: str):
    return page.evaluate(
        """
        (routeName) => {
          const issues = [];
          const duplicateIds = [];
          const seen = new Map();
          document.querySelectorAll('[id]').forEach((node) => {
            const id = node.id;
            seen.set(id, (seen.get(id) || 0) + 1);
          });
          for (const [id, count] of seen.entries()) {
            if (count > 1) duplicateIds.push(id);
          }
          if (duplicateIds.length) {
            issues.push({
              severity: 'P1',
              text: `Duplicate id attributes detected: ${duplicateIds.slice(0, 5).join(', ')}`
            });
          }

          if (!document.getElementById('themeToggle')) {
            issues.push({ severity: 'P2', text: 'Theme toggle is missing from the rendered page.' });
          }

          if (document.documentElement.scrollWidth > window.innerWidth + 4) {
            issues.push({ severity: 'P1', text: 'Horizontal overflow detected in the rendered viewport.' });
          }

          const unlabeled = Array.from(document.querySelectorAll('input, select, textarea'))
            .filter((field) => {
              if (!field.name || field.type === 'hidden') return false;
              if (field.closest('.sr-only')) return false;
              if (field.labels && field.labels.length) return false;
              if (field.getAttribute('aria-label') || field.getAttribute('aria-labelledby')) return false;
              return true;
            }).length;
          if (unlabeled) {
            issues.push({ severity: 'P2', text: `${unlabeled} form control(s) do not have an associated label.` });
          }

          const inlineStyles = document.querySelectorAll('[style]').length;
          if (inlineStyles > 10) {
            issues.push({ severity: 'P3', text: `${inlineStyles} inline style attributes are still present on the page.` });
          }

          const inlineHandlers = document.querySelectorAll('[onclick]').length;
          if (inlineHandlers > 0) {
            issues.push({ severity: 'P2', text: `${inlineHandlers} inline click handlers are still present on the page.` });
          }

          const genericPlaceholders = Array.from(document.querySelectorAll('input[placeholder], textarea[placeholder]'))
            .filter((field) => /type something/i.test(field.getAttribute('placeholder') || '')).length;
          if (genericPlaceholders) {
            issues.push({ severity: 'P3', text: `${genericPlaceholders} field(s) still use the generic placeholder "Type something...".` });
          }

          const tinyTargets = Array.from(document.querySelectorAll('button, a, input[type="checkbox"], input[type="radio"]'))
            .filter((node) => {
              const rect = node.getBoundingClientRect();
              return rect.width > 0 && rect.height > 0 && (rect.width < 36 || rect.height < 36);
            }).length;
          if (tinyTargets > 0 && window.innerWidth <= 430) {
            issues.push({ severity: 'P2', text: `${tinyTargets} touch target(s) are smaller than 36px in the mobile viewport.` });
          }

          if (routeName.startsWith('plugin_') && !document.querySelector('[data-settings-schema]')) {
            issues.push({ severity: 'P2', text: 'Plugin page is still using the legacy handwritten settings body.' });
          }

          if (!document.querySelector('[data-page-shell]')) {
            issues.push({ severity: 'P2', text: 'Shared page-shell marker is missing from the rendered page.' });
          }

          const primaryActions = document.querySelectorAll('.action-button.primary, .workflow-action-group .action-button.primary');
          if (primaryActions.length > 1) {
            issues.push({ severity: 'P2', text: 'More than one primary call-to-action is visible in the current action area.' });
          }

          return issues;
        }
        """,
        route_name,
    )


def create_runtime_tracker(page, base_url: str):
    tracker = {
        "console_errors": [],
        "page_errors": [],
        "request_failures": [],
        "response_failures": [],
    }
    page.on("pageerror", lambda exc: tracker["page_errors"].append(str(exc)))

    def handle_console(msg):
        if msg.type != "error":
            return
        text = msg.text
        if "integrity" in text and "leaflet" in text.lower():
            return
        tracker["console_errors"].append(text)

    page.on("console", handle_console)
    page.on(
        "requestfailed",
        lambda request: (
            tracker["request_failures"].append(
                {
                    "url": request.url,
                    "resource_type": request.resource_type,
                    "failure": request.failure or "",
                }
            )
            if request.url.startswith(base_url)
            and request.resource_type
            in {"document", "script", "stylesheet", "xhr", "fetch"}
            else None
        ),
    )
    page.on(
        "response",
        lambda response: (
            tracker["response_failures"].append(
                {
                    "url": response.url,
                    "status": response.status,
                    "resource_type": response.request.resource_type,
                }
            )
            if response.url.startswith(base_url)
            and response.status >= 400
            and response.request.resource_type
            in {"document", "script", "stylesheet", "xhr", "fetch"}
            else None
        ),
    )
    return tracker


def collect_runtime_issues(tracker):
    issues = []
    if tracker["page_errors"]:
        issues.append(
            {
                "severity": "P1",
                "text": f"Uncaught page errors detected: {tracker['page_errors'][:3]}",
            }
        )
    if tracker["console_errors"]:
        issues.append(
            {
                "severity": "P1",
                "text": f"Console errors detected: {tracker['console_errors'][:3]}",
            }
        )
    if tracker["request_failures"]:
        issues.append(
            {
                "severity": "P1",
                "text": f"Critical request failures detected: {tracker['request_failures'][:3]}",
            }
        )
    if tracker["response_failures"]:
        issues.append(
            {
                "severity": "P1",
                "text": f"Critical HTTP failures detected: {tracker['response_failures'][:3]}",
            }
        )
    return issues


def capture_route(
    browser, base_url: str, route_name: str, route_path: str, output_dir: Path
):
    matrix = []
    for viewport_name, cfg in VIEWPORTS.items():
        print(f"[capture] {route_name} {viewport_name}", flush=True)
        context = browser.new_context(
            viewport={"width": cfg["width"], "height": cfg["height"]},
            color_scheme=cfg["scheme"],
            is_mobile=cfg["mobile"],
            device_scale_factor=2 if cfg["mobile"] else 1,
        )
        scoped_page = context.new_page()
        stub_external_assets(scoped_page)
        tracker = create_runtime_tracker(scoped_page, base_url)
        screenshot_path = output_dir / f"{route_name}__{viewport_name}.png"
        try:
            scoped_page.goto(
                f"{base_url}{route_path}", wait_until="commit", timeout=15000
            )
            scoped_page.wait_for_timeout(1200)
            scoped_page.screenshot(
                path=str(screenshot_path), full_page=True, timeout=5000
            )
            issues = collect_dom_issues(scoped_page, route_name)
            issues.extend(collect_runtime_issues(tracker))
        except PlaywrightTimeoutError:
            issues = [
                {
                    "severity": "P1",
                    "text": f"Route timed out while loading: {route_path}",
                }
            ]
        except Exception as exc:
            issues = [
                {
                    "severity": "P1",
                    "text": f"Route failed during audit capture: {type(exc).__name__}",
                }
            ]
        matrix.append(
            {
                "route": route_path,
                "route_name": route_name,
                "viewport": viewport_name,
                "screenshot": str(screenshot_path),
                "issues": issues,
            }
        )
        context.close()
    return matrix


def build_backlog(matrix: list[dict]) -> list[dict]:
    backlog = []
    index = 1
    for capture in matrix:
        for issue in capture["issues"]:
            backlog.append(
                {
                    "id": index,
                    "severity": issue["severity"],
                    "route": capture["route"],
                    "viewport": capture["viewport"],
                    "screenshot": capture["screenshot"],
                    "issue": issue["text"],
                }
            )
            index += 1
    return backlog


def write_artifacts(output_dir: Path, matrix: list[dict]):
    backlog = build_backlog(matrix)
    (output_dir / "audit_matrix.json").write_text(json.dumps(matrix, indent=2))
    (output_dir / "audit_backlog.json").write_text(json.dumps(backlog, indent=2))
    lines = ["# UI Audit Backlog", ""] + [
        f"{item['id']}. [{item['severity']}] `{item['route']}` `{item['viewport']}` - {item['issue']} ({item['screenshot']})"
        for item in backlog
    ]
    if not backlog:
        lines.append("No issues detected by the automated heuristics.")
    (output_dir / "audit_backlog.md").write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Capture a batched UI audit backlog.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--output-dir", default="runtime/mock_display_output/ui_audit")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    output_dir = (repo_root / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    routes = [Scenario(name, path) for name, path in TOP_LEVEL_ROUTES]
    plugin_ids = discover_plugin_ids(repo_root)
    for plugin_id in plugin_ids:
        routes.extend(
            Scenario(f"plugin_{plugin_id}_{scenario.name}", scenario.path)
            for scenario in create_plugin_scenarios(args.base_url, plugin_id)
        )

    matrix = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for scenario in routes:
            print(f"[route] {scenario.name} -> {scenario.path}", flush=True)
            matrix.extend(
                capture_route(
                    browser, args.base_url, scenario.name, scenario.path, output_dir
                )
            )
            write_artifacts(output_dir, matrix)
        browser.close()
    write_artifacts(output_dir, matrix)


if __name__ == "__main__":
    main()
