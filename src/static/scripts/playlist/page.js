(function (global) {
  const ns = (global.InkyPiPlaylist = global.InkyPiPlaylist || {});

  function hideThumbnail(img) {
    img.style.display = "none";
    const skeleton = img.previousElementSibling;
    if (skeleton) skeleton.style.display = "none";
    img.dataset.loaded = "1";
  }

  function initDeviceClock() {
    const val = document.getElementById("currentTimeValue");
    if (!val) return;

    function render() {
      const now = new Date();
      const browserOffsetMin = -now.getTimezoneOffset();
      const adjustMs =
        ((ns.config.device_tz_offset_min || 0) - browserOffsetMin) * 60000;
      const devNow = new Date(now.getTime() + adjustMs);
      val.textContent = devNow.toLocaleString(undefined, { hour12: false });
    }

    render();
    if (!ns.runtime.deviceClockTimer) {
      ns.runtime.deviceClockTimer = global.setInterval(render, 1000);
    }
  }

  function initThumbnailPreviewHandlers() {
    document.querySelectorAll(".plugin-thumbnail-container").forEach((box) => {
      if (box.dataset.playlistPreviewBound === "1") return;
      box.addEventListener("click", (event) => {
        const target = event.currentTarget;
        ns.showThumbnailPreview(
          target.dataset.thumbnailPlaylist,
          target.dataset.thumbnailPlugin,
          target.dataset.thumbnailDisplayName,
          target.dataset.thumbnailInstance,
          target.dataset.thumbnailInstanceLabel
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
    document.querySelectorAll(".plugin-thumb").forEach((box) => {
      box.style.cursor = "zoom-in";
      box.setAttribute("role", "button");
      box.setAttribute("tabindex", "0");
    });
    if (!global.Lightbox) return;

    global.Lightbox.bind(".plugin-thumb", {
      getUrl: (el) => {
        const img = el.querySelector("img");
        return img?.src && img.style.display !== "none" ? img.src : null;
      },
      getAlt: (el) => {
        const img = el.querySelector("img");
        return img?.alt || "Preview";
      },
    });
  }

  async function loadThumb(img) {
    if (img.dataset.loaded === "1") return;

    const url = img.dataset.src;
    if (
      !url ||
      !/^\/static\/[A-Za-z0-9._\-/]+(\?[A-Za-z0-9._\-=&%]*)?$/.test(url)
    ) {
      hideThumbnail(img);
      return;
    }

    try {
      const resp = await fetch(url, { method: "HEAD" });
      if (!resp.ok) throw new Error("thumbnail missing");
      img.src = url;
      img.style.display = "";
      img.dataset.loaded = "1";
    } catch (error) {
      console.debug("Playlist thumbnail unavailable:", error);
      hideThumbnail(img);
    }
  }

  function initLazyThumbnails() {
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
  }

  function initPageEnhancements() {
    if (ns.runtime.pageEnhancementsBound) return;
    initThumbnailPreviewHandlers();
    initLightboxThumbs();
    initLazyThumbnails();
    initDeviceClock();

    ns.runtime.pageEnhancementsBound = true;
  }

  Object.assign(ns, {
    initDeviceClock,
    initLazyThumbnails,
    initLightboxThumbs,
    initPageEnhancements,
    initThumbnailPreviewHandlers,
    loadThumb,
  });
})(globalThis);
