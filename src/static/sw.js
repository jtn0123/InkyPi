const CACHE_NAME = "inkypi-shell-v1";

const SHELL_ASSETS = [
  "/static/styles/main.css",
  "/static/scripts/theme.js",
  "/static/scripts/csrf.js",
  "/static/scripts/client_errors.js",
  "/static/scripts/form_validator.js",
  "/static/scripts/response_modal.js",
  "/static/scripts/ui_helpers.js",
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

  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) {
        return cached;
      }
      return fetch(request).then((response) => {
        if (!response || response.status !== 200) {
          return response;
        }
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
        return response;
      });
    })
  );
});
