const CACHE_NAME = "inkypi-shell-v24";

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

  // Only handle same-origin GET requests to /static/*
  if (
    request.method !== "GET" ||
    !request.url.startsWith(self.location.origin + "/static/")
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
