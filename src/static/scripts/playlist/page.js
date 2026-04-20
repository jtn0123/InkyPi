(function (global) {
  const ns = (global.InkyPiPlaylist = global.InkyPiPlaylist || {});

  function initDeviceClock() {
    const val = document.getElementById("currentTimeValue");
    if (!val) return;

    function render() {
      try {
        const now = new Date();
        const browserOffsetMin = -now.getTimezoneOffset();
        const adjustMs =
          ((ns.config.device_tz_offset_min || 0) - browserOffsetMin) * 60000;
        const devNow = new Date(now.getTime() + adjustMs);
        val.textContent = devNow.toLocaleString(undefined, { hour12: false });
      } catch (_err) {}
    }

    render();
    if (!ns.runtime.deviceClockTimer) {
      ns.runtime.deviceClockTimer = global.setInterval(render, 1000);
    }
  }

  function renderNextIn() {
    document.querySelectorAll(".plugin-item").forEach((item) => {
      const infoEl = item.querySelector(".plugin-info");
      if (!infoEl) return;

      const intervalSecAttr = item.getAttribute("data-interval-sec");
      const lastIsoAttr = item.getAttribute("data-latest-iso");
      const intervalSec = intervalSecAttr ? parseInt(intervalSecAttr, 10) : NaN;
      if (!intervalSec || isNaN(intervalSec)) return;

      const lastDate = (() => {
        try {
          return lastIsoAttr ? new Date(lastIsoAttr) : null;
        } catch (_err) {
          return null;
        }
      })();
      if (!lastDate) return;

      const nextTs = lastDate.getTime() + intervalSec * 1000;
      const deltaMs = nextTs - Date.now();
      const nextEl = infoEl.querySelector(".latest-refresh");
      if (!nextEl || deltaMs <= 0) return;

      const mins = Math.round(deltaMs / 60000);
      if (mins < 60) {
        nextEl.textContent = `Refreshed • Next in ${mins} min`;
        return;
      }

      const hrs = Math.floor(mins / 60);
      const rem = mins % 60;
      nextEl.textContent = `Refreshed • Next in ${hrs}h ${rem}m`;
    });
  }

  function initThumbnailPreviewHandlers() {
    document.querySelectorAll(".plugin-thumbnail-container").forEach((box) => {
      if (box.dataset.playlistPreviewBound === "1") return;
      box.addEventListener("click", (event) => {
        const target = event.currentTarget;
        ns.showThumbnailPreview(
          target.getAttribute("data-thumbnail-playlist"),
          target.getAttribute("data-thumbnail-plugin"),
          target.getAttribute("data-thumbnail-display-name"),
          target.getAttribute("data-thumbnail-instance"),
          target.getAttribute("data-thumbnail-instance-label")
        );
      });

      box.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        box.click();
      });
      box.dataset.playlistPreviewBound = "1";
    });

    document.querySelectorAll(".plugin-thumbnail").forEach((img) => {
      if (img.dataset.playlistPreviewBound === "1") return;
      img.addEventListener("load", () => {
        const skeleton = img.previousElementSibling;
        if (skeleton) skeleton.style.display = "none";
        img.hidden = false;
      });
      img.addEventListener("error", () => {
        const container = img.closest(".plugin-thumbnail-container");
        if (container) container.hidden = true;
      });
      img.dataset.playlistPreviewBound = "1";
    });
  }

  function initLightboxThumbs() {
    try {
      document.querySelectorAll(".plugin-thumb").forEach((box) => {
        box.style.cursor = "zoom-in";
        box.setAttribute("role", "button");
        box.setAttribute("tabindex", "0");
      });
      if (!global.Lightbox) return;

      global.Lightbox.bind(".plugin-thumb", {
        getUrl: (el) => {
          const img = el.querySelector("img");
          return img && img.src && img.style.display !== "none" ? img.src : null;
        },
        getAlt: (el) => {
          const img = el.querySelector("img");
          return (img && img.alt) || "Preview";
        },
      });
    } catch (_err) {}
  }

  async function loadThumb(img) {
    if (img.getAttribute("data-loaded") === "1") return;

    const url = img.getAttribute("data-src");
    if (
      !url ||
      !/^\/static\/[A-Za-z0-9._\-/]+(\?[A-Za-z0-9._\-=&%]*)?$/.test(url)
    ) {
      img.style.display = "none";
      const skeleton = img.previousElementSibling;
      if (skeleton) skeleton.style.display = "none";
      img.setAttribute("data-loaded", "1");
      return;
    }

    try {
      const resp = await fetch(url, { method: "HEAD" });
      if (!resp.ok) throw new Error("thumbnail missing");
      img.src = url;
      img.style.display = "";
      img.setAttribute("data-loaded", "1");
    } catch (_err) {
      img.style.display = "none";
      const skeleton = img.previousElementSibling;
      if (skeleton) skeleton.style.display = "none";
      img.setAttribute("data-loaded", "1");
    }
  }

  function initLazyThumbnails() {
    try {
      const thumbs = Array.from(
        document.querySelectorAll(".plugin-thumb img[data-src]")
      );
      if (!thumbs.length) return;

      if (!("IntersectionObserver" in global)) {
        thumbs.forEach((img) => {
          loadThumb(img);
        });
        return;
      }

      const observer = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (!entry.isIntersecting) return;
            const img = entry.target;
            observer.unobserve(img);
            loadThumb(img);
          });
        },
        {
          rootMargin: ns.mobileQuery.matches
            ? "50px"
            : ns.constants.THUMB_PREFETCH_MARGIN,
        }
      );

      thumbs.forEach((img) => observer.observe(img));
    } catch (_err) {}
  }

  function initPageEnhancements() {
    if (ns.runtime.pageEnhancementsBound) return;
    initThumbnailPreviewHandlers();
    initLightboxThumbs();
    initLazyThumbnails();

    try {
      initDeviceClock();
      renderNextIn();
      if (!ns.runtime.nextInTimer) {
        ns.runtime.nextInTimer = global.setInterval(
          renderNextIn,
          ns.constants.NEXT_IN_REFRESH_MS
        );
      }
    } catch (_err) {}

    ns.runtime.pageEnhancementsBound = true;
  }

  Object.assign(ns, {
    initDeviceClock,
    initLazyThumbnails,
    initLightboxThumbs,
    initPageEnhancements,
    initThumbnailPreviewHandlers,
    loadThumb,
    renderNextIn,
  });
})(globalThis);
