// One way for page scripts to ask the server for JSON.
//
// fetchJson(url, init) checks the status before it trusts the body, so a
// proxy's 502 page, a sign-in page or a dropped connection turns into a
// sentence the page can show, never "Unexpected token '<' ... is not valid
// JSON". It resolves to the parsed body and rejects with a FetchJsonError
// whose message is the server's own `error` (or `message`) when it sent one.
// A body of {"success": false, ...} counts as a failure whatever the status.
// An aborted request still rejects with the browser's AbortError, so callers
// that cancel requests can tell the two apart.
(function () {
  "use strict";

  const NETWORK_MESSAGE =
    "Couldn't reach InkyPi. Check that it is running and on the network, then try again.";
  const UNREADABLE_MESSAGE =
    "InkyPi sent a reply this page couldn't read. Reload the page and try again.";
  const SIGNED_OUT_MESSAGE =
    "Your sign-in has expired. Reload the page to sign in again.";
  const FALLBACK_MESSAGE = "Something went wrong. Please try again.";

  function statusMessage(status, endpoint) {
    const ctx = endpoint ? ` (${endpoint})` : "";
    const messages = {
      400: `Invalid request${ctx}. Please check your input.`,
      401: `Authentication required${ctx}. Please log in.`,
      403: `Access denied${ctx}. You don't have permission.`,
      404: `Resource not found${ctx}.`,
      408: `Request timed out${ctx}. Please try again.`,
      429: `Too many requests${ctx}. Please wait a moment and retry.`,
      500: `Server error${ctx}. Please try again later.`,
      502: `Service temporarily unavailable${ctx}. Retry in a few seconds.`,
      503: `Service unavailable${ctx}. Retry in a few seconds.`,
      504: `Gateway timeout${ctx}. Retry in a few seconds.`,
    };
    return messages[status] || `An unexpected error occurred${ctx}. Please try again.`;
  }

  // kind is "network" (no reply), "http" (an error status, or a body that
  // says success: false) or "unreadable" (a success status whose body is not
  // JSON).
  class FetchJsonError extends Error {
    constructor(message, { kind, status = 0, data = null, response = null, cause } = {}) {
      super(message, cause === undefined ? undefined : { cause });
      this.name = "FetchJsonError";
      this.kind = kind;
      this.status = status;
      this.data = data;
      this.response = response;
      this.requestId = typeof data?.request_id === "string" ? data.request_id : null;
    }
  }

  function isAbort(error) {
    return error?.name === "AbortError" || error?.name === "TimeoutError";
  }

  function serverMessage(data) {
    for (const key of ["error", "message"]) {
      const value = data?.[key];
      if (typeof value === "string" && value.trim()) return value;
    }
    return "";
  }

  function wasSentToSignIn(response) {
    try {
      return response.redirected && new URL(response.url).pathname === "/login";
    } catch {
      return false;
    }
  }

  // Read a Response the caller already has (for one that needs its status,
  // such as a 202 that starts a background job). Same rules as fetchJson.
  async function readJson(response) {
    let text;
    try {
      text = await response.text();
    } catch (cause) {
      if (isAbort(cause)) throw cause;
      throw new FetchJsonError(NETWORK_MESSAGE, { kind: "network", response, cause });
    }
    let data = null;
    let parsed = true;
    if (text.trim()) {
      try {
        data = JSON.parse(text);
      } catch {
        parsed = false;
      }
    }
    const status = response.status;
    if (!response.ok || (parsed && data?.success === false)) {
      const body = parsed ? data : null;
      throw new FetchJsonError(serverMessage(body) || statusMessage(status), {
        kind: "http",
        status,
        data: body,
        response,
      });
    }
    if (!parsed || (data === null && status !== 204)) {
      const message = wasSentToSignIn(response) ? SIGNED_OUT_MESSAGE : UNREADABLE_MESSAGE;
      throw new FetchJsonError(message, { kind: "unreadable", status, response });
    }
    return data;
  }

  async function fetchJson(url, init = {}) {
    const headers = new Headers(init.headers);
    // Error handlers answer in JSON when asked to, so failures carry the
    // server's own words instead of an HTML error page.
    if (!headers.has("Accept")) headers.set("Accept", "application/json");
    let response;
    try {
      response = await fetch(url, { ...init, headers });
    } catch (cause) {
      if (isAbort(cause)) throw cause;
      throw new FetchJsonError(NETWORK_MESSAGE, { kind: "network", cause });
    }
    return readJson(response);
  }

  // The text to show for a failed request. A reply from the server (an error
  // status or an unreadable body) is described by its FetchJsonError; anything
  // else (no reply, or a bug in the page) gets the caller's own wording.
  function errorMessage(error, fallback) {
    if (error instanceof FetchJsonError && error.kind !== "network") {
      return error.message;
    }
    if (fallback) return fallback;
    return error instanceof FetchJsonError ? error.message : FALLBACK_MESSAGE;
  }

  globalThis.InkyPiHttp = Object.freeze({
    FetchJsonError,
    errorMessage,
    fetchJson,
    readJson,
    statusMessage,
  });
  // Called by bare name from many page scripts (listed in biome.json).
  globalThis.fetchJson = fetchJson;
})();
