const CACHE_NAME = "inkypi-shell-v25";

// Mirrors _PUBLIC_STATIC_DIRS in src/app_setup/auth.py. Other /static/
// subtrees (e.g. images/) can hold private display images and require login,
// so they must never be persisted in the shared offline cache.
const PUBLIC_STATIC_PATH = /^\/static\/(?:dist|fonts|icons|scripts|styles|vendor)\//;

const SHELL_ASSETS = [
  "/static/styles/main.css",
  "/static/scripts/theme.js",
  "/static/scripts/csrf.js",
  "/static/scripts/client_errors.js",
  "/static/scripts/form_validator.js",
  "/static/scripts/response_modal.js",
  "/static/scripts/ui_helpers.js",
  "/static/scripts/tweaks_panel.js",
  "/static/scripts/update_indicator.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS))
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key.startsWith("inkypi-shell-") && key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;

  // Only handle same-origin GET requests to public /static/ asset subtrees
  if (
    request.method !== "GET" ||
    !request.url.startsWith(self.location.origin + "/static/") ||
    !PUBLIC_STATIC_PATH.test(new URL(request.url).pathname)
  ) {
    return;
  }

  event.respondWith((async () => {
    const cache = await caches.open(CACHE_NAME);
    const cached = await cache.match(request);
    const path = new URL(request.url).pathname;
    // Only build-generated content hashes make cache-first safe across updates.
    const immutable = /^\/static\/dist\/common\.bundle\.[a-f0-9]{8}\.(?:min\.)?(?:js|css)$/.test(path);
    if (immutable && cached) return cached;

    let response;
    try {
      // Revalidate the browser's HTTP cache as well as the worker's cache.
      response = await fetch(request, { cache: "no-cache" });
    } catch (error) {
      if (cached) return cached;
      throw error;
    }
    if (response?.status === 200) {
      // A full/unavailable offline cache must not hide a successful download.
      await cache.put(request, response.clone()).catch(() => {});
    }
    return response;
  })());
});
